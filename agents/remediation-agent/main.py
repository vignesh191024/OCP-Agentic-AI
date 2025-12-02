import os
import requests
import threading
from flask import Flask, request, jsonify
from kubernetes import client, config
from slack_sdk import WebClient
from slack_sdk.models.blocks import SectionBlock, HeaderBlock

# --- Configuration ---
REFLECTION_AGENT_URL = os.environ.get("REFLECTION_AGENT_URL", "http://reflection-agent-svc:8080/log")
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
        print("Warning: Could not load in-cluster config (local dev?)")

load_kube_config()
core_v1 = client.CoreV1Api()
apps_v1 = client.AppsV1Api()

# --- Helper: Slack Notification ---
def notify_slack_start(action, target):
    try:
        blocks = [
            HeaderBlock(text=":tools: Remediation Agent"),
            SectionBlock(text=f"I received the order. Executing `{action}` on `{target}` now...")
        ]
        slack_client.chat_postMessage(channel=SLACK_CHANNEL, blocks=blocks, text="Remediation Started")
    except Exception as e:
        print(f"Slack Error: {e}")

# --- Tools ---
def delete_pod(name, namespace):
    print(f"Restarting pod {name} in {namespace}...")
    core_v1.delete_namespaced_pod(name=name, namespace=namespace)
    return True, f"Deleted pod {name}"

def scale_up(name, namespace):
    print(f"Scaling up deployment {name} in {namespace}...")
    scale = apps_v1.read_namespaced_deployment_scale(name, namespace)
    current_replicas = scale.spec.replicas
    if current_replicas is None: current_replicas = 0
    
    # Scale up by 1
    scale.spec.replicas = current_replicas + 1
    apps_v1.replace_namespaced_deployment_scale(name, namespace, scale)
    return True, f"Scaled {name} from {current_replicas} to {scale.spec.replicas} replicas"

# --- Main Logic ---
def perform_remediation(plan):
    action = plan.get("action")
    ns = plan.get("namespace")
    
    # Intelligent Target Selection
    if action == "scale_up":
        target = plan.get("deployment_name")
    else:
        target = plan.get("pod_name")

    # 1. Announce to Slack
    notify_slack_start(action, target)

    # 2. Do the work
    try:
        if action == "restart_pod":
            success, msg = delete_pod(target, ns)
        elif action == "scale_up":
            success, msg = scale_up(target, ns)
        else:
            success, msg = True, "No action needed (Dry Run)"
    except Exception as e:
        success, msg = False, str(e)

    # 3. Handoff to Reflection Agent
    print(f"Work done. Handing off to Reflection Agent: {msg}")
    try:
        requests.post(REFLECTION_AGENT_URL, json={
            "remediation_plan": plan, 
            "status": "success" if success else "failure", 
            "message": msg
        }, timeout=5)
    except Exception as e:
        print(f"Failed to call Reflection Agent: {e}")

# --- API Endpoints ---
@app.route('/remediate', methods=['POST'])
def remediate_endpoint():
    threading.Thread(target=perform_remediation, args=(request.json,)).start()
    return jsonify({"status": "accepted"}), 200

if __name__ == '__main__':
    print("--- STARTING REMEDIATION AGENT V4 (SCALE UP SUPPORT) ---", flush=True)
    app.run(host='0.0.0.0', port=8080)
