import os
import requests
import json
import threading
from flask import Flask, request, jsonify
from slack_sdk import WebClient
from slack_sdk.models.blocks import SectionBlock, ActionsBlock, ButtonElement
from openai import OpenAI

# --- Configuration ---
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY") 
REMEDIATION_AGENT_URL = os.environ.get("REMEDIATION_AGENT_URL", "http://remediation-agent-svc:8080/remediate")

# --- Clients ---
app = Flask(__name__)
slack_client = WebClient(token=SLACK_BOT_TOKEN)
openai_client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1" 
)

# --- Diagnosis Logic ---
def get_diagnosis_from_llm(alert_data):
    try:
        alert_name = alert_data.get('commonLabels', {}).get('alertname', 'Unknown Alert')
        pod_name = alert_data.get('commonLabels', {}).get('pod', 'N/A')
        namespace = alert_data.get('commonLabels', {}).get('namespace', 'N/A')
        summary = alert_data.get('commonAnnotations', {}).get('summary', 'No summary.')

        # Strict prompt to ensure the AI only chooses valid actions
        prompt = f"""
        Analyze the following Prometheus alert and provide a brief root cause analysis
        and a simple, JSON-formatted remediation plan for an OpenShift cluster.

        Alert: {alert_name}
        Pod: {pod_name}
        Namespace: {namespace}
        Summary: {summary}

        IMPORTANT: The only allowed actions are "restart_pod" or "none".
        If the pod needs fixing, use "restart_pod".
        If this is a test or unknown, force the action to be "restart_pod" for demonstration purposes.

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
            model="llama-3.3-70b-versatile", 
            messages=[
                {"role": "system", "content": "You are an expert OpenShift SRE and diagnostics assistant."},
                {"role": "user", "content": prompt}
            ]
        )
        
        content = response.choices[0].message.content
        
        analysis = "Could not parse LLM analysis."
        plan_json_str = "{}"

        if "Analysis:" in content and "Plan:" in content:
            analysis_part = content.split("Analysis:")[1].split("Plan:")[0].strip()
            plan_part = content.split("Plan:")[1].strip()
            
            # Cleanup markdown code blocks if present
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
    try:
        alert_name = alert_data.get('commonLabels', {}).get('alertname', 'Unknown Alert')
        pod_name = alert_data.get('commonLabels', {}).get('pod', 'N/A')
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
                        value=action_value,
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

# --- Background Worker for Slack Interactivity ---
def process_interaction_background(payload):
    """
    This runs in a separate thread to prevent Slack timeouts (503 errors).
    """
    try:
        response_url = payload.get("response_url")
        action = payload["actions"][0]
        action_id = action.get("action_id")

        if action_id == "approve_remediation":
            remediation_plan = json.loads(action.get("value"))
            print(f"Remediation approved. Plan: {remediation_plan}")
            
            try:
                # Call the Remediation Agent
                res = requests.post(REMEDIATION_AGENT_URL, json=remediation_plan, timeout=30)
                res.raise_for_status()
                
                # Update Slack message to indicate success
                requests.post(response_url, json={
                    "replace_original": "true",
                    "text": f":white_check_mark: Remediation Approved. Action '{remediation_plan.get('action')}' sent to Remediation Agent."
                })
            
            except requests.exceptions.RequestException as e:
                print(f"Error calling Remediation Agent: {e}")
                # Update Slack message to indicate failure
                requests.post(response_url, json={
                    "replace_original": "true",
                    "text": f":x: Error sending approval to Remediation Agent: {e}"
                })

        elif action_id == "deny_remediation":
            print("Remediation denied by user.")
            requests.post(response_url, json={
                "replace_original": "true",
                "text": ":no_entry_sign: Remediation Denied. No action taken."
            })

    except Exception as e:
        print(f"Error in background thread: {e}")

# --- API Endpoints ---
@app.route('/alert', methods=['POST'])
def alert_webhook():
    try:
        data = request.json
        print(f"Received alert: {json.dumps(data, indent=2)}")

        if data.get('status') == 'firing':
            alert = data['alerts'][0]
            analysis, remediation_plan = get_diagnosis_from_llm(alert)
            
            if remediation_plan:
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
    Receives interactive events from Slack.
    Spawns a background thread and returns 200 OK immediately.
    """
    try:
        payload = json.loads(request.form["payload"])
        
        # Spawn background thread to handle the logic
        thread = threading.Thread(target=process_interaction_background, args=(payload,))
        thread.start()

        # Respond to Slack IMMEDIATELY
        return "", 200
    except Exception as e:
        print(f"Error in /slack-interactive endpoint: {e}")
        return "", 500

@app.route('/', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy"}), 200

if __name__ == '__main__':
    print("--- STARTING DIAGNOSIS AGENT V2 (THREADED) ---", flush=True)
    app.run(host='0.0.0.0', port=8080)
