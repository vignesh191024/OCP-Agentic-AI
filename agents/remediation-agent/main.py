import os
import json
import requests
from flask import Flask, request, jsonify
from kubernetes import client, config

# --- Configuration ---
REFLECTION_AGENT_URL = os.environ.get("REFLECTION_AGENT_URL", "http://reflection-agent-svc:8080/log")

# --- Clients ---
app = Flask(__name__)

# --- Kubernetes Client Setup ---
def load_kube_config():
    """
    Loads Kubernetes config. In-cluster config is used when running inside a pod,
    otherwise, it falls back to the local kubeconfig file for testing.
    """
    try:
        config.load_incluster_config()
        print("Loaded in-cluster Kubernetes config.")
    except config.ConfigException:
        try:
            config.load_kube_config()
            print("Loaded local Kubernetes config (fallback).")
        except config.ConfigException:
            print("Could not load any Kubernetes config.")
            return None
    return client.CoreV1Api()

core_v1_api = load_kube_config()

# --- Remediation Actions ---
def delete_pod(pod_name, namespace, reason):
    """
    Deletes a specific pod in a specific namespace.
    This effectively "restarts" the pod if it's managed by a Deployment.
    """
    if not core_v1_api:
        return False, "Kubernetes API client not initialized."
        
    print(f"Attempting to delete pod (to restart): {pod_name} in namespace: {namespace} for reason: {reason}")
    try:
        core_v1_api.delete_namespaced_pod(
            name=pod_name,
            namespace=namespace,
            body=client.V1DeleteOptions()
        )
        success_msg = f"Successfully deleted pod {pod_name} in {namespace} to trigger restart."
        print(success_msg)
        return True, success_msg
    except client.ApiException as e:
        error_msg = f"Error deleting pod: {e}"
        print(error_msg)
        return False, error_msg

# --- Logging to Reflection Agent ---
def log_to_reflection_agent(plan, success, message):
    """
    Sends the result of the remediation to the Reflection Agent.
    """
    try:
        log_data = {
            "remediation_plan": plan,
            "status": "success" if success else "failure",
            "message": message
        }
        requests.post(REFLECTION_AGENT_URL, json=log_data, timeout=5)
    except Exception as e:
        print(f"Error logging to Reflection Agent: {e}")

# --- API Endpoints ---
@app.route('/remediate', methods=['POST'])
def remediate_endpoint():
    """
    Receives remediation plan and executes it.
    """
    try:
        plan = request.json
        print(f"Received remediation plan: {plan}")
        
        action = plan.get("action")
        pod_name = plan.get("pod_name")
        namespace = plan.get("namespace")
        reason = plan.get("reason", "No reason provided.")
        
        success = False
        message = "No action taken."

        if action == "restart_pod":
            if pod_name and namespace:
                # The 'delete_pod' function is the technical implementation of 'restart_pod'
                success, message = delete_pod(pod_name, namespace, reason)
            else:
                message = "Missing 'pod_name' or 'namespace' for restart_pod action."
        
        elif action == "none":
            success = True
            message = "Action 'none' requested. No remediation performed."
            
        else:
            message = f"Unknown action: {action}"

        # Log the outcome
        log_to_reflection_agent(plan, success, message)

        if success:
            return jsonify({"status": "success", "message": message}), 200
        else:
            return jsonify({"status": "error", "message": message}), 500

    except Exception as e:
        print(f"Error in /remediate endpoint: {e}")
        # Log failure
        log_to_reflection_agent(request.json, False, str(e))
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
