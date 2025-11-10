import os
import requests
import json
from flask import Flask, request, jsonify
from slack_sdk import WebClient
from slack_sdk.models.blocks import SectionBlock, ActionsBlock, ButtonElement
from openai import OpenAI

# --- Configuration ---
# Load from environment variables
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
# Internal OpenShift service URLs
REMEDIATION_AGENT_URL = os.environ.get("REMEDIATION_AGENT_URL", "http://remediation-agent-svc:8080/remediate")

# --- Clients ---
app = Flask(__name__)
slack_client = WebClient(token=SLACK_BOT_TOKEN)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# --- Diagnosis Logic ---
def get_diagnosis_from_llm(alert_data):
    """
    Queries OpenAI to get a diagnosis and a remediation plan.
    """
    try:
        alert_name = alert_data.get('commonLabels', {}).get('alertname', 'Unknown Alert')
        pod_name = alert_data.get('commonLabels', {}).get('pod', 'N/A')
        namespace = alert_data.get('commonLabels', {}).get('namespace', 'N/A')
        summary = alert_data.get('commonAnnotations', {}).get('summary', 'No summary.')

        # Future Enhancement: Query Loki for logs
        # lokl_query = f'{{pod="{pod_name}", namespace="{namespace}"}}'
        # logs = "Example logs..." 

        prompt = f"""
        Analyze the following Prometheus alert and provide a brief root cause analysis
        and a simple, JSON-formatted remediation plan for an OpenShift cluster.

        Alert: {alert_name}
        Pod: {pod_name}
        Namespace: {namespace}
        Summary: {summary}

        Example Remediation JSON:
        {{
          "action": "restart_pod",
          "pod_name": "{pod_name}",
          "namespace": "{namespace}",
          "reason": "Pod is in a crash loop and requires a restart."
        }}
        
        Provide only the root cause analysis as a string and the JSON plan.
        Start the analysis with "Analysis:" and the JSON with "Plan:".
        """

        response = openai_client.chat.completions.create(
            model="gpt-4o-mini", # Using a cost-effective and fast model
            messages=[
                {"role": "system", "content": "You are an expert OpenShift SRE and diagnostics assistant."},
                {"role": "user", "content": prompt}
            ]
        )
        
        content = response.choices[0].message.content
        
        # Parse the LLM's structured response
        analysis = "Could not parse LLM analysis."
        plan_json_str = "{}"

        if "Analysis:" in content and "Plan:" in content:
            analysis_part = content.split("Analysis:")[1].split("Plan:")[0].strip()
            plan_part = content.split("Plan:")[1].strip()
            
            # Clean up the JSON string (LLMs sometimes add markdown)
            if plan_part.startswith("```json"):
                plan_part = plan_part[7:]
            if plan_part.endswith("```"):
                plan_part = plan_part[:-3]
                
            analysis = analysis_part
            plan_json_str = plan_part
        
        return analysis, json.loads(plan_json_str)

    except Exception as e:
        print(f"Error in LLM Diagnosis: {e}")
        return f"Error during analysis: {e}", None

def send_slack_approval(alert_data, analysis, remediation_plan):
    """
    Sends an interactive message to Slack for remediation approval.
    """
    try:
        alert_name = alert_data.get('commonLabels', {}).get('alertname', 'Unknown Alert')
        pod_name = alert_data.get('commonLabels', {}).get('pod', 'N/A')
        
        # Serialize the plan to send with the button's 'value' field
        action_value = json.dumps(remediation_plan)

        blocks = [
            SectionBlock(text=f":rotating_light: *New OpenShift Alert: {alert_name}*"),
            SectionBlock(
                text=f"*Analysis from AI:* {analysis}",
                fields=[
                    f"*Pod:* {pod_name}",
                    f"*Namespace:* {alert_data.get('commonLabels', {}).get('namespace', 'N/A')}",
                    f"*Summary:* {alert_data.get('commonAnnotations', {}).get('summary', 'No summary.')}",
                    f"*Proposed Action:* {remediation_plan.get('action', 'none')}"
                ]
            ),
            ActionsBlock(
                elements=[
                    ButtonElement(
                        text="Approve Remediation",
                        style="primary",
                        action_id="approve_remediation",
                        value=action_value, # Send the full plan
                        confirm={
                            "title": "Confirm Action",
                            "text": f"Are you sure you want to run: {remediation_plan.get('action')} on {pod_name}?",
                            "confirm": "Approve",
                            "deny": "Cancel"
                        }
                    ),
                    ButtonElement(
                        text="Deny",
                        style="danger",
                        action_id="deny_remediation",
                        value="denied"
                    )
                ]
            )
        ]
        
        slack_client.chat_postMessage(
            channel=SLACK_CHANNEL,
            blocks=blocks,
            text=f"Alert: {alert_name} - {analysis}"
        )
    except Exception as e:
        print(f"Error sending Slack message: {e}")

# --- API Endpoints ---
@app.route('/alert', methods=['POST'])
def alert_webhook():
    """
    Receives alerts from Alertmanager.
    This is the main entry point.
    """
    try:
        data = request.json
        print(f"Received alert: {json.dumps(data, indent=2)}")

        if data.get('status') == 'firing':
            # Process the first alert in the batch
            alert = data['alerts'][0]
            
            # 1. Get Diagnosis
            analysis, remediation_plan = get_diagnosis_from_llm(alert)
            
            if remediation_plan:
                # 2. Send for Manual Approval
                send_slack_approval(alert, analysis, remediation_plan)
            else:
                print(f"No remediation plan generated for {alert.get('commonLabels')}")

        return jsonify({"status": "success"}), 200
    except Exception as e:
        print(f"Error in /alert endpoint: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/slack-interactive', methods=['POST'])
def slack_interactive_endpoint():
    """
    Receives interactive events from Slack (e.g., button clicks).
    """
    try:
        # Slack sends data as form-encoded 'payload'
        payload = json.loads(request.form["payload"])
        
        # Check if it's a block action (button click)
        if payload.get("type") == "block_actions":
            action = payload["actions"][0]
            action_id = action.get("action_id")
            
            response_url = payload.get("response_url")
            
            if action_id == "approve_remediation":
                # User clicked "Approve"
                remediation_plan = json.loads(action.get("value"))
                
                print(f"Remediation approved. Plan: {remediation_plan}")
                
                # Send approval to Remediation Agent
                try:
                    res = requests.post(REMEDIATION_AGENT_URL, json=remediation_plan, timeout=10)
                    res.raise_for_status()
                    
                    # Update original Slack message to show completion
                    requests.post(response_url, json={
                        "replace_original": "true",
                        "text": f":white_check_mark: Remediation Approved. Action '{remediation_plan.get('action')}' sent to Remediation Agent."
                    })
                
                except requests.exceptions.RequestException as e:
                    print(f"Error calling Remediation Agent: {e}")
                    requests.post(response_url, json={
                        "replace_original": "true",
                        "text": f":x: Error sending approval to Remediation Agent: {e}"
                    })

            elif action_id == "deny_remediation":
                # User clicked "Deny"
                print("Remediation denied by user.")
                # Update original Slack message
                requests.post(response_url, json={
                    "replace_original": "true",
                    "text": ":no_entry_sign: Remediation Denied. No action taken."
                })

        return "", 200
    except Exception as e:
        print(f"Error in /slack-interactive endpoint: {e}")
        return "", 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)

