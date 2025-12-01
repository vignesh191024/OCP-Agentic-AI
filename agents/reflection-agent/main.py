import os
import json
import time
import threading
from flask import Flask, request, jsonify
from slack_sdk import WebClient
from slack_sdk.models.blocks import SectionBlock, HeaderBlock, DividerBlock, ContextBlock
from kubernetes import client, config

# --- Configuration ---
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL")

# --- Clients ---
app = Flask(__name__)
slack_client = WebClient(token=SLACK_BOT_TOKEN)

# --- Kubernetes Client ---
def load_kube_config():
    try:
        config.load_incluster_config()
    except:
        print("Warning: Could not load in-cluster config")

load_kube_config()
core_v1 = client.CoreV1Api()
apps_v1 = client.AppsV1Api()

# --- Verification Logic ---
def verify_fix(plan, status, message):
    if status != "success":
        slack_client.chat_postMessage(
            channel=SLACK_CHANNEL, 
            text=f"❌ **Reflection Agent:** Remediation failed. Error: {message}"
        )
        return

    # Wait for K8s to settle
    print("Verification: Waiting 15 seconds for cluster to stabilize...")
    time.sleep(15)
    
    action = plan.get('action')
    ns = plan.get('namespace', 'default')
    
    # Extract diagnosis context
    diagnosis_data = plan.get('diagnosis_report', {})
    analysis_text = diagnosis_data.get('analysis', 'No analysis available')
    logs_text = diagnosis_data.get('logs', '') 
    
    # Safety Check for missing logs
    if logs_text is None: logs_text = "(No logs available)"

    # Truncate logs
    logs_lines = logs_text.splitlines()
    final_logs_snippet = "\n".join(logs_lines[-3:]) if len(logs_lines) > 3 else logs_text

    try:
        verification_details = ""
        status_emoji = ":white_check_mark:"
        
        if action == "restart_pod":
            # Verify Pod Restart
            pods = core_v1.list_namespaced_pod(ns, label_selector="app=deploy-one")
            if pods.items:
                newest = sorted(pods.items, key=lambda p: p.metadata.creation_timestamp, reverse=True)[0]
                verification_details = (f"*Action:* Pod Restart\n"
                                        f"*New Pod:* `{newest.metadata.name}`\n"
                                        f"*Status:* `{newest.status.phase}`")
            else:
                verification_details = "*Action:* Pod Restart (No pods found?)"
                        
        elif action == "scale_up":
            # Verify Scale Up (Check Deployment)
            name = plan.get("deployment_name", "deploy-one")
            try:
                scale = apps_v1.read_namespaced_deployment_scale(name, ns)
                verification_details = (f"*Action:* Scale Up\n"
                                        f"*Target:* `{name}`\n"
                                        f"*New Replica Count:* `{scale.status.replicas}`")
            except Exception as e:
                verification_details = f"Failed to verify scale up: {e}"
        
        # --- FINAL REPORT ---
        blocks = [
            HeaderBlock(text=f"{status_emoji} Incident Resolved"),
            DividerBlock(),
            SectionBlock(text=f"*:detective: Diagnosis Agent Analysis:*\n>{analysis_text}"),
            SectionBlock(text=f"*Logs:* `{final_logs_snippet}`"),
            DividerBlock(),
            SectionBlock(text=f"*:tools: Remediation Agent Action:*\nExecuted `{action}` successfully.\n_{message}_"),
            DividerBlock(),
            SectionBlock(text=f"*:white_check_mark: Reflection Agent Verification:*\n{verification_details}"),
            ContextBlock(elements=[{"type": "mrkdwn", "text": "✅ Full self-healing cycle complete."}])
        ]
        
        slack_client.chat_postMessage(channel=SLACK_CHANNEL, blocks=blocks, text="Incident Resolved")
                        
    except Exception as e:
        print(f"Error in verification: {e}")
        slack_client.chat_postMessage(
            channel=SLACK_CHANNEL, 
            text=f"⚠️ **Reflection Agent:** Remediation executed, but verification failed: {e}"
        )

# --- API Endpoints ---
@app.route('/log', methods=['POST'])
def log_endpoint():
    try:
        data = request.json
        print(f"Logging incident: {json.dumps(data, indent=2)}")
        threading.Thread(target=verify_fix, args=(
            data.get('remediation_plan'), 
            data.get('status'), 
            data.get('message')
        )).start()
        return jsonify({"status": "logged"}), 200
    except Exception as e:
        print(f"Error in /log endpoint: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    print("--- STARTING REFLECTION AGENT V5 (ROBUST VERIFICATION) ---", flush=True)
    app.run(host='0.0.0.0', port=8080)
