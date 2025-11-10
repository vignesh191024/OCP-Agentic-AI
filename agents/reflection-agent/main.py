import os
import json
from flask import Flask, request, jsonify
from slack_sdk import WebClient

# --- Configuration ---
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL")

# --- Clients ---
app = Flask(__name__)
slack_client = WebClient(token=SLACK_BOT_TOKEN)

# --- API Endpoints ---
@app.route('/log', methods=['POST'])
def log_endpoint():
    """
    Receives log data from the Remediation Agent and notifies Slack.
    """
    try:
        data = request.json
        # This is where you would save to a Vector DB for future learning
        print(f"Logging incident: {json.dumps(data, indent=2)}")
        
        # --- Notify Slack ---
        status = data.get("status", "unknown")
        message = data.get("message", "No message.")
        plan = data.get("remediation_plan", {})
        action = plan.get("action", "none")

        if status == "success":
            color = "#36a64f" # good
            icon = ":white_check_mark:"
            title = f"Remediation Successful: `{action}`"
        else:
            color = "#danger" # danger
            icon = ":x:"
            title = f"Remediation Failed: `{action}`"

        attachment = {
            "color": color,
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"{icon} *{title}*"
                    }
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Pod:*\n`{plan.get('pod_name', 'N/A')}`"},
                        {"type": "mrkdwn", "text": f"*Namespace:*\n`{plan.get('namespace', 'N/A')}`"},
                        {"type": "mrkdwn", "text": f"*Status:*\n`{status}`"},
                        {"type": "mrkdwn", "text": f"*Details:*\n`{message}`"}
                    ]
                }
            ]
        }
        
        slack_client.chat_postMessage(
            channel=SLACK_CHANNEL,
            attachments=[attachment],
            text=f"{title}: {message}"
        )

        return jsonify({"status": "logged"}), 200
    except Exception as e:
        print(f"Error in /log endpoint: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
