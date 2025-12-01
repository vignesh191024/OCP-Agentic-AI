import os
import requests
import json
import threading
import re
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
    # Safety Check: If pod name is missing, N/A, or looks like a deployment name (no hash), skip logs
    if not pod_name or pod_name == 'N/A' or pod_name == 'None':
        return "(No pod name provided to fetch logs - Pod likely missing)"
    
    try:
        print(f"Investigating: Fetching logs for {pod_name} in {namespace}...", flush=True)
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
        # Extract Labels
        labels = alert_data.get('labels', {})
        annotations = alert_data.get('annotations', {})

        alert_name = labels.get('alertname', 'Unknown Alert')
        namespace = labels.get('namespace', 'vigneshbaskar-dev') 
        
        # --- SMART NAME DETECTION ---
        # 1. Try explicit labels
        pod_name = labels.get('pod')
        # Prometheus often sends 'deployment' label for deployment alerts
        deployment_name = labels.get('deployment') or labels.get('deploymentconfig') or labels.get('app')

        # 2. If Pod is missing, try to infer Deployment from common labels
        if not pod_name:
            pod_name = "N/A"
            # If we don't have a deployment name yet, check 'instance' or 'service'
            if not deployment_name:
                deployment_name = labels.get('instance') or labels.get('service')

        summary = annotations.get('summary', 'No summary.')
        description = annotations.get('message', annotations.get('description', 'No description.'))

        # 1. Autonomous Investigation
        pod_logs = get_pod_logs(pod_name if "N/A" not in pod_name else None, namespace)

        # 2. Agentic Prompt with STRICTER Logic
        prompt = f"""
        You are an expert OpenShift SRE. Analyze the alert and recommend a fix.

        CONTEXT:
        Alert: {alert_name}
        Pod: {pod_name}
        Deployment: {deployment_name}
        Logs: {pod_logs}

        CRITICAL DECISION RULES (Follow Priority Order):
        1. PRIORITY 1: IF Pod Name is 'N/A', 'None', or matches the Deployment Name exactly -> This means the deployment is scaled to 0. Action MUST be "scale_up".
        2. PRIORITY 2: IF Alert is 'DeploymentReplicasZero' -> Action: "scale_up".
        3. PRIORITY 3: IF Pod Name exists (e.g., has a suffix like -xyz) AND (Logs show errors OR Alert is 'PodDown') -> Action: "restart_pod".
        
        Example Remediation JSON:
        {{
          "action": "scale_up",
          "pod_name": "{pod_name}",
          "namespace": "{namespace}",
          "deployment_name": "{deployment_name if deployment_name else 'deploy-one'}",
          "reason": "Pod Name is N/A. Deployment is likely scaled down. Scaling up to restore service."
        }}
        
        Provide "Analysis:" and "Plan:" (JSON only).
        """

        print(f"Sending prompt to LLM for {alert_name}...", flush=True)

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
        
        try:
            plan = json.loads(plan_json_str)
        except json.JSONDecodeError:
            print("Failed to decode JSON plan from LLM")
            plan = {}
        
        # Fallback: If logic completely fails to capture deployment name
        if "deployment_name" not in plan or not plan["deployment_name"]: 
             plan["deployment_name"] = "deploy-one"

        plan['diagnosis_report'] = {
            "analysis": analysis[:800],
            "logs": pod_logs[:500]
        }

        return analysis, plan, pod_logs

    except Exception as e:
        print(f"Error in LLM Diagnosis: {e}")
        return f"Error: {e}", None, ""

def send_slack_approval(analysis, plan, logs):
    try:
        log_lines = logs.splitlines()
        short_logs = "\n".join(log_lines[-5:]) if len(log_lines) > 5 else logs
        
        action = plan.get('action', 'Unknown Action')
        # Display the correct target based on action
        if action == "scale_up":
            target = plan.get('deployment_name', 'Unknown Deployment')
        else:
            target = plan.get('pod_name', 'Unknown Pod')

        blocks = [
            HeaderBlock(text=":detective: Diagnosis Agent"),
            SectionBlock(text=f"I detected an issue. My analysis:\n>{analysis}"),
            SectionBlock(fields=[
                {"type": "mrkdwn", "text": f"*Target:*\n`{target}`"},
                {"type": "mrkdwn", "text": f"*Recommended Action:*\n`{action}`"}
            ]),
            SectionBlock(text=f"*Evidence (Logs/State):*\n```{short_logs}```"),
            ActionsBlock(
                elements=[
                    ButtonElement(
                        text="Approve Fix",
                        style="primary",
                        action_id="approve_remediation",
                        value=json.dumps(plan),
                        confirm={
                            "title": "Confirm Action",
                            "text": f"Are you sure you want to run: {action}?",
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
            text=f"Alert Diagnosis: {action}"
        )
    except Exception as e:
        print(f"Error sending Slack message: {e}")

# --- Background Worker ---
def bg_worker(payload):
    resp_url = payload.get("response_url")
    action_id = payload["actions"][0]["action_id"]
    
    existing_blocks = payload["message"]["blocks"]
    if existing_blocks:
        existing_blocks.pop() 

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
            print(f"Sending plan to Remediation Agent: {plan}")
            requests.post(REMEDIATION_AGENT_URL, json=plan, timeout=5)
        except Exception as e:
            print(f"Failed to contact remediation agent: {e}")
    else:
        existing_blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": ":no_entry_sign: **Request Denied.** No action taken."}
        })
        requests.post(resp_url, json={"replace_original": "true", "blocks": existing_blocks})

@app.route('/alert', methods=['POST'])
def alert():
    data = request.json
    print(f"Received Alertmanager Payload: {json.dumps(data)}", flush=True)

    if data.get('status') == 'firing':
        for alert_item in data.get('alerts', []):
            analysis, plan, logs = get_diagnosis_from_llm(alert_item)
            if plan: 
                send_slack_approval(analysis, plan, logs)
                
    return jsonify({"status": "processed"}), 200

@app.route('/slack-interactive', methods=['POST'])
def interactive():
    threading.Thread(target=bg_worker, args=(json.loads(request.form["payload"]),)).start()
    return "", 200

@app.route('/', methods=['GET'])
def health(): return "Diagnosis Agent Active", 200

if __name__ == '__main__':
    print("--- STARTING DIAGNOSIS AGENT V11 (DEPLOYMENT GENERIC FIX) ---", flush=True)
    app.run(host='0.0.0.0', port=8080)
