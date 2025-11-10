OCP Pods: Application workloads deployed in OCP.

Prometheus: For metrics collection from OCP pods.

Grafana: For visualization of metrics.

Alertmanager: To receive alerts from Prometheus and route them to receivers.

Agentic AI: To automatically act on alerts and perform tasks.



OCP Pods
   │
   ▼
Prometheus (Scrapes metrics from pods)
   │
   ▼
Alertmanager (Receives alerts from Prometheus)
   │
   ▼
Webhook Receiver → Agentic AI (Automates manual tasks)
   │
   ▼
Grafana (Optional visualization of metrics & alerts)

-----

# OCP Agentic AI Self-Healing Project

This project implements an agentic AI workflow on OpenShift to provide self-healing capabilities. It uses a multi-agent system (Diagnosis, Remediation, Reflection) to analyze Prometheus alerts, propose solutions via an LLM, and execute fixes (like restarting pods) after human approval via Slack.

This guide provides the steps to deploy and configure the agents on your OpenShift cluster.

## Prerequisites

Before you begin, you must have:

1.  An OpenShift project. This guide is pre-configured for: `vigneshbaskar-dev`
2.  A Slack Bot Token. This guide is pre-configured for: `xoxb-9864777158599-9876928775285-JgWbaGmqnrH0eH5tucgKX8Us`
3.  A Slack Channel. This guide is pre-configured for: `#openshift-alerts`
4.  An OpenAI API Key. You will need to provide this.

-----

## Step 1: Configure Alertmanager

The first step is to tell your existing Alertmanager to send alerts to the new AI agents.

1.  **Edit the `alert-manager-config.yml` file** in the root of this repository.
2.  Replace the entire contents of the file with the code below. This adds a new `ai_diagnostics` receiver and sets it as the default.

**Complete File: `alert-manager-config.yml`**

```yaml
global:
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
    - api_url: 'https://hooks.slack.com/services/...' # (This is your original placeholder)
      channel: '#vignesh-dev'
      send_resolved: true

inhibit_rules:
- source_match:
    severity: 'critical'
  target_match:
    severity: 'warning'
  equal: ['alertname', 'dev', 'instance']
```

3.  **Apply the configuration change** to your cluster. This command updates the `alertmanager-main` ConfigMap from your local file:
    ```bash
    # Run this from the root of your OCP-Agentic-AI repository
    oc create configmap alertmanager-main --from-file=alert-manager-config.yml -o yaml --dry-run=client | oc replace -f -
    ```
4.  The Alertmanager pod will automatically reload the new configuration.

-----

## Step 2: Create Secrets and ConfigMaps

The agents need your API keys and Slack channel name. Run these commands in your WSL terminal.

```bash
# Create the secret for your API keys
# I've added your Slack token. You just need to add your OpenAI key.
oc create secret generic ai-secrets \
  --from-literal=OPENAI_API_KEY='sk-...' \
  --from-literal=SLACK_BOT_TOKEN='xoxb-9864777158599-9876928775285-JgWbaGmqnrH0eH5tucgKX8Us'

# Create the ConfigMap for your Slack channel
# I've added your '#openshift-alerts' channel.
oc create configmap agent-config \
  --from-literal=SLACK_CHANNEL='#openshift-alerts'
```

-----

## Step 3: Build and Deploy Agents

Now, build and deploy the three agents. The `kubernetes.yaml` files in the repo are already pre-filled with your project name (`vigneshbaskar-dev`).

Run these commands from the **root** of your `OCP-Agentic-AI` repository.

```bash
# === Build and Deploy Diagnosis Agent ===
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
```

-----

## Step 4: Configure Slack App for Interactivity

The final step is to tell Slack where to send the "Approve" / "Deny" button clicks.

1.  Expose the `diagnosis-agent` service with a public route:

    ```bash
    oc expose svc/diagnosis-agent-svc
    ```

2.  Get the new public URL for your route:

    ```bash
    oc get route diagnosis-agent-svc -o jsonpath='{.spec.host}'
    ```

3.  Go to your Slack App's configuration page (at `api.slack.com`).

4.  Click on **"Interactivity & Shortcuts"** in the sidebar.

5.  Turn **Interactivity ON**.

6.  In the **"Request URL"** box, paste your public URL from Step 2, and add `/slack-interactive` at the end.
    *Example: `https://diagnosis-agent-svc-vigneshbaskar-dev.apps.sandbox-m2.ll9k.p1.openshiftapps.com/slack-interactive`*

7.  Save your changes.

Your system is now fully deployed. When Prometheus fires an alert, it will trigger the full AI diagnosis and remediation workflow.
