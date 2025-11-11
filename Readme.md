OCP Agentic AI Self-Healing ProjectThis project implements an agentic AI workflow on OpenShift to provide self-healing capabilities. It uses a multi-agent system (Diagnosis, Remediation, Reflection) to analyze Prometheus alerts, propose solutions via Llama 3, and execute fixes (like restarting pods) after human approval via Slack.This guide provides the steps to deploy and configure the agents on your OpenShift cluster.PrerequisitesBefore you begin, you must have:An OpenShift project. This guide is pre-configured for: vigneshbaskar-devA Slack Channel. This guide is pre-configured for: #openshift-alertsThe oc (OpenShift CLI) and git command-line tools installed.Step 1: Get API Keys & TokensYou will need two secret keys to run this project.1.A: Get Your Groq (Llama) API KeyWe are using Groq to get free, high-speed access to the Llama 3 model.Go to groq.com and sign up for a free account.Once logged in, click on your account in the top-right and select "API Keys".Click "Create API Key".Give it a name (e.g., openshift-agent) and click "Create".Copy the key immediately. It will start with gsk_.... You will use this in Step 3.1.B: Get Your Slack Bot TokenYou need to create a Slack App to act as your bot.Go to api.slack.com/apps and click "Create New App".Choose "From scratch".Name your app (e.g., OpenShift Agent) and select your test workspace.In the left sidebar, click on "OAuth & Permissions".Scroll down to the "Scopes" section.Under "Bot Token Scopes", click "Add an OAuth Scope" and add:chat:write: To post messages.chat:write.public: To post in public channels.Scroll back to the top and click "Install to Workspace", then click "Allow".Copy the "Bot User OAuth Token". It will start with xoxb-.... You will use this in Step 3.Finally, go to your #openshift-alerts channel in Slack and invite your bot by typing /invite @OpenShift Agent (or whatever you named your app).Step 2: Configure AlertmanagerThis step tells your existing Alertmanager to send all alerts to your new AI agent.Ensure your alert-manager-config.yml file (in the root of this repo) is updated with the code below. This adds a new ai_diagnostics receiver and sets it as the default.File: alert-manager-config.ymlglobal:
  resolve_timeout: 5m
route:
  group_by: ['alertname']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 1h
  # 1. The default receiver is now 'ai_diagnostics'
  receiver: 'ai_diagnostics' 
receivers:
  # 2. This new receiver sends alerts to our Python agent
  - name: 'ai_diagnostics'
    webhook_configs:
      - url: 'http://diagnosis-agent-svc:8080/alert'
        send_resolved: true

  # 3. This is your original receiver, kept as a backup.
  - name: 'slack-notifications'
    slack_configs:
    - api_url: '[https://hooks.slack.com/services/](https://hooks.slack.com/services/)...' # (This is your original placeholder)
      channel: '#vignesh-dev'
      send_resolved: true

inhibit_rules:
- source_match:
    severity: 'critical'
  target_match:
    severity: 'warning'
  equal: ['alertname', 'dev', 'instance']
Apply the configuration change to your cluster. This command updates the alertmanager-main ConfigMap from your local file:# Run this from the root of your OCP-Agentic-AI repository
oc create configmap alertmanager-main --from-file=alert-manager-config.yml -o yaml --dry-run=client | oc replace -f -
The Alertmanager pod will automatically reload the new configuration.Step 3: Create Secrets and ConfigMapsNow, use the keys you generated in Step 1 to create the Kubernetes secrets.# Create the secret for your API keys
# Replace the placeholders with the keys you just copied
oc create secret generic ai-secrets \
  --from-literal=GROQ_API_KEY='gsk_YOUR_KEY_HERE' \
  --from-literal=SLACK_BOT_TOKEN='xoxb_YOUR_TOKEN_HERE'

# Create the ConfigMap for your Slack channel (this is unchanged)
oc create configmap agent-config \
  --from-literal=SLACK_CHANNEL='#openshift-alerts'
Step 4: Build and Deploy AgentsThis step builds your agent code and deploys it to OpenShift. The kubernetes.yaml files in the repo are already pre-filled with your project name (vigneshbaskar-dev).Run these commands from the root of your OCP-Agentic-AI repository.# === Build and Deploy Diagnosis Agent ===
cd agents/diagnosis-agent

oc new-build --name=diagnosis-agent --binary --strategy=docker
oc start-build diagnosis-agent --from-dir=. --follow
oc apply -f kubernetes.yaml

# Go back to the root
cd ../..

# === Build and Deploy Remediation Agent ===
cd agents/remediation-agent

oc new-build --name=remediation-agent --binary --strategy=docker
oc start-build remediation-agent --from-dir=. --follow
oc apply -f kubernetes.yaml

# Go back to the root
cd ../..

# === Build and Deploy Reflection Agent ===
cd agents/reflection-agent

oc new-build --name=reflection-agent --binary --strategy=docker
oc start-build reflection-agent --from-dir=. --follow
oc apply -f kubernetes.yaml

# Go back to the root
cd ../..
Step 5: Configure Slack App for InteractivityThe final step is to tell Slack where to send the "Approve" / "Deny" button clicks.Expose the diagnosis-agent service with a public route:oc expose svc/diagnosis-agent-svc
Get the new public URL for your route:oc get route diagnosis-agent-svc -o jsonpath='{.spec.host}'
Go to your Slack App's configuration page at api.slack.com.Click on "Interactivity & Shortcuts" in the sidebar.Turn Interactivity ON.In the "Request URL" box, paste your public URL from Step 2, and add /slack-interactive at the end.Example: https://diagnosis-agent-svc-vigneshbaskar-dev.apps.sandbox-m2.ll9k.p1.openshiftapps.com/slack-interactiveSave your changes.Your system is now fully deployed. When Prometheus fires an alert, it will trigger the full AI diagnosis and remediation workflow using Llama 3.
