import os
import requests
import json
import threading
from flask import Flask, request, jsonify
from slack_sdk import WebClient
from slack_sdk.models.blocks import SectionBlock, ActionsBlock, ButtonElement, DividerBlock, HeaderBlock
from openai import OpenAI
from kubernetes import client, config

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

# --- Kubernetes Client ---
def load_kube_config():
    try:
        config.load_incluster_config()
    except:
        print("Warning: Could not load in-cluster config (local dev?)")

load_kube_config()
core_v1 = client.CoreV1Api()

# --- Helper: Fetch Logs ---
def get_pod_logs(pod_name, namespace):
    """
    Agentic Tool: Fetches the last 20 lines of logs.
    """
    try:
        print(f"Investigating: Fetching logs for {pod_name}...")
        pod = core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
        container_name = pod.spec.containers[0].name
        for c in pod.spec.containers:
            if c.name == 'app':
                container_name = 'app'
                break
        logs = core_v1.read_namespaced_pod_log(
            name=pod_name, 
            namespace=namespace, 
            container=container_name, 
            tail_lines=20
        )
        return logs
    except Exception as e:
        return f"(Logs unavailable: {str(e)})"

# --- Diagnosis Logic ---
def get_diagnosis_from_llm(alert_data):
    try:
        alert_name = alert_data.get('commonLabels', {}).get('alertname', 'Unknown Alert')
        pod_name = alert_data.get('commonLabels', {}).get('pod', 'N/A')
        namespace = alert_data.get('commonLabels', {}).get('namespace', 'N/A')
        summary = alert_data.get('commonAnnotations', {}).get('summary', 'No summary.')

        # 1. Autonomous Investigation
        pod_logs = get_pod_logs(pod_name, namespace)

        # 2. Agentic Prompt
        prompt = f"""
        You are an expert OpenShift SRE. I need you to analyze an alert and the pod logs to recommend a fix.

        ALERT DETAILS:
        Name: {alert_name}
        Pod: {pod_name}
        Summary: {summary}

        INVESTIGATION LOGS (Last 20 lines):
        -----------------------------------
        {pod_logs}
        -----------------------------------

        Based on the alert AND the logs, determine the root cause.
        
        DECISION LOGIC:
        1. If logs show errors (Crash, OOM, Exception) OR alert is 'PodDown' -> Action: "restart_pod"
        2. If logs look healthy but alert is 'HighCPU' or 'HighLoad' -> Action: "scale_up"
        
        Example Remediation JSON:
        {{
          "action": "restart_pod" OR "scale_up",
          "pod_name": "{pod_name}",
          "namespace": "{namespace}",
          "deployment_name": "deploy-one",
          "reason": "Logs indicate a deadlock/crash. Restarting to recover."
        }}
        
        Provide the analysis (referencing the logs) and the JSON plan.
        Start the analysis with "Analysis:" and the JSON with "Plan:".
        """

        response = openai_client.chat.completions.create(
            model="llama-3.3-70b-versatile", 
            messages=[
                {"role": "system", "content": "You are a helpful SRE assistant."},
                {"role": "user", "content": prompt}
            ]
        )
        
        content = response.choices[0].message.content
        
        analysis = "Could not parse LLM analysis."
        plan_json_str = "{}"

        if "Analysis:" in content and "Plan:" in content:
            analysis_part = content.split("Analysis:")[1].split("Plan:")[0].strip()
            plan_part = content.split("Plan:")[1].strip()
            if plan_part.startswith("```json"):
                plan_part = plan_part[7:]
            if plan_part.endswith("```"):
                plan_part = plan_part[:-3]
            analysis = analysis_part
            plan_json_str = plan_part
        
        # Parse the JSON plan
        plan = json.loads(plan_json_str)
        
        # Fallback for deployment name
        if "deployment_name" not in plan: plan["deployment_name"] = "deploy-one"

        # --- CRITICAL: Inject Data for Downstream Agents ---
        plan['diagnosis_report'] = {
            "analysis": analysis[:800], # Truncate for Slack limits
            "logs": pod_logs[:500]      # Truncate for Slack limits
        }

        return analysis, plan, pod_logs

    except Exception as e:
        print(f"Error in LLM Diagnosis: {e}")
        return f"Error: {e}", None, ""

def send_slack_approval(analysis, plan, logs):
    try:
        log_lines = logs.splitlines()
        short_logs = "\n".join(log_lines[-5:]) if len(log_lines) > 5 else logs
        
        blocks = [
            HeaderBlock(text=":detective: Diagnosis Agent"),
            SectionBlock(text=f"I detected an issue. My analysis:\n>{analysis}"),
            SectionBlock(fields=[
                {"type": "mrkdwn", "text": f"*Target:*\n`{plan.get('pod_name')}`"},
                {"type": "mrkdwn", "text": f"*Recommended Action:*\n`{plan.get('action')}`"}
            ]),
            SectionBlock(text=f"*Evidence (Logs):*\n```{short_logs}```"),
            ActionsBlock(
                elements=[
                    ButtonElement(
                        text="Approve Fix",
                        style="primary",
                        action_id="approve_remediation",
                        value=json.dumps(plan),
                        confirm={
                            "title": "Confirm Action",
                            "text": f"Are you sure you want to run: {plan.get('action')}?",
                            "confirm": "Yes, Fix It",
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
            text=f"Alert: {plan.get('action')}"
        )
    except Exception as e:
        print(f"Error sending Slack message: {e}")

# --- Background Worker ---
def bg_worker(payload):
    resp_url = payload.get("response_url")
    action_id = payload["actions"][0]["action_id"]
    
    existing_blocks = payload["message"]["blocks"]
    if existing_blocks:
        existing_blocks.pop() # Remove buttons

    if action_id == "approve_remediation":
        plan = json.loads(payload["actions"][0]["value"])
        user = payload["user"]["username"]

        existing_blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":white_check_mark: **Approved by @{user}.**\nHanding off to **Remediation Agent**..."
            }
        })
        
        requests.post(resp_url, json={"replace_original": "true", "blocks": existing_blocks})
        
        try:
            requests.post(REMEDIATION_AGENT_URL, json=plan, timeout=5)
        except: pass
    else:
        existing_blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": ":no_entry_sign: **Request Denied.** No action taken."}
        })
        requests.post(resp_url, json={"replace_original": "true", "blocks": existing_blocks})

# --- API Endpoints ---
@app.route('/alert', methods=['POST'])
def alert():
    data = request.json
    if data.get('status') == 'firing':
        analysis, plan, logs = get_diagnosis_from_llm(data['alerts'][0])
        if plan: send_slack_approval(analysis, plan, logs)
    return "", 200

@app.route('/slack-interactive', methods=['POST'])
def interactive():
    threading.Thread(target=bg_worker, args=(json.loads(request.form["payload"]),)).start()
    return "", 200

@app.route('/', methods=['GET'])
def health(): return "", 200

if __name__ == '__main__':
    print("--- STARTING DIAGNOSIS AGENT V7 (DATA PASSING) ---", flush=True)
    app.run(host='0.0.0.0', port=8080)
