# 🤖 OCP Agentic AI Self-Healing Project

This project implements an **Agentic AI workflow on OpenShift** to provide **self-healing capabilities**.
It uses a **multi-agent system** — **Diagnosis**, **Remediation**, and **Reflection** — to analyze **Prometheus alerts**, propose solutions via **Llama 3**, and execute fixes (like restarting pods) after **human approval via Slack**.

This guide provides the steps to deploy and configure the agents on your OpenShift cluster.

---

## 🧩 Prerequisites

Before you begin, make sure you have:

* ✅ An **OpenShift project** — preconfigured for: `vigneshbaskar-dev`
* 💬 A **Slack channel** — preconfigured for: `#openshift-alerts`
* 🧰 Installed CLI tools:

  * `oc` (OpenShift CLI)
  * `git`

---

## ⚙️ Step 1: Get API Keys & Tokens

You will need two secret keys to run this project.

### 1A. Get Your Groq (Llama) API Key

We use **Groq** for free, high-speed access to the **Llama 3** model.

1. Go to [https://groq.com](https://groq.com) and sign up for a free account.
2. Click your account → **API Keys** → **Create API Key**.
3. Name it (e.g. `openshift-agent`) → click **Create**.
4. Copy the key (starts with `gsk_...`).
   You’ll use this in **Step 3**.

---

### 1B. Get Your Slack Bot Token

You’ll create a Slack App to act as your bot.

1. Go to [https://api.slack.com/apps](https://api.slack.com/apps) → **Create New App → From scratch**.
2. Name your app (e.g. `OpenShift Agent`) → select your test workspace.
3. In the left sidebar, go to **OAuth & Permissions**.
4. Under **Bot Token Scopes**, add:

   * `chat:write`
   * `chat:write.public`
5. Click **Install to Workspace** → **Allow**.
6. Copy your **Bot User OAuth Token** (starts with `xoxb_...`).
   You’ll use this in **Step 3**.
7. Finally, in Slack run:

   ```
   /invite @OpenShift Agent
   ```

   (or whatever you named your bot).

---

## 🚨 Step 2: Configure Alertmanager

This step updates **Alertmanager** to send all alerts to your new AI agent.

Update your `alert-manager-config.yml` (found in the repo root) with:

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
      - api_url: 'https://hooks.slack.com/services/...'
        channel: '#vignesh-dev'
        send_resolved: true

inhibit_rules:
- source_match:
    severity: 'critical'
  target_match:
    severity: 'warning'
  equal: ['alertname', 'dev', 'instance']
```

Then apply the configuration to your cluster:

```bash
# Run from the repo root
oc create configmap alertmanager-main \
  --from-file=alertmanager.yml=alertmanager-config.yaml \
  -o yaml --dry-run=client | oc apply -f -
```

The Alertmanager pod will automatically reload the new configuration.

---

## 🔐 Step 3: Create Secrets and ConfigMaps

Use the keys you generated in Step 1 to create the Kubernetes secrets.

```bash
# Create the secret for your API keys
oc create secret generic ai-secrets \
  --from-literal=GROQ_API_KEY='gsk_YOUR_KEY_HERE' \
  --from-literal=SLACK_BOT_TOKEN='xoxb_YOUR_TOKEN_HERE'

# Create the ConfigMap for your Slack channel
oc create configmap agent-config \
  --from-literal=SLACK_CHANNEL='#openshift-alerts'
```

---

## 🚀 Step 4: Build and Deploy Agents

Build and deploy all three agents.
The `kubernetes.yaml` files are already preconfigured for the project: **vigneshbaskar-dev**.

### Diagnosis Agent

```bash
cd agents/diagnosis-agent
oc new-build --name=diagnosis-agent --binary --strategy=docker
oc start-build diagnosis-agent --from-dir=. --follow
oc apply -f kubernetes.yaml
cd ../..
```

### Remediation Agent

```bash
cd agents/remediation-agent
oc new-build --name=remediation-agent --binary --strategy=docker
oc start-build remediation-agent --from-dir=. --follow
oc apply -f kubernetes.yaml
cd ../..
```

### Reflection Agent

```bash
cd agents/reflection-agent
oc new-build --name=reflection-agent --binary --strategy=docker
oc start-build reflection-agent --from-dir=. --follow
oc apply -f kubernetes.yaml
cd ../..
```

---

## 💬 Step 5: Configure Slack App for Interactivity

Enable interactive approval (Approve/Deny) buttons in Slack.

1. Expose the `diagnosis-agent` service:

   ```bash
   oc expose svc/diagnosis-agent-svc
   ```

2. Get the route URL:

   ```bash
   oc get route diagnosis-agent-svc -o jsonpath='{.spec.host}'
   ```

3. In your Slack App page ([api.slack.com](https://api.slack.com)):

   * Go to **Interactivity & Shortcuts**.
   * Turn **Interactivity** ON.
   * Set **Request URL** to:

     ```
     https://<your-route-host>/slack-interactive
     ```

   Example:

   ```
   https://diagnosis-agent-svc-vigneshbaskar-dev.apps.sandbox-m2.ll9k.p1.openshiftapps.com/slack-interactive
   ```

4. Click **Save Changes**.

---

## ✅ System Ready!

🎉 Your system is now fully deployed!

When **Prometheus fires an alert**, it triggers the full **AI-driven diagnosis and remediation workflow** using **Llama 3** — automatically proposing fixes, requesting approval in Slack, and executing self-healing actions.

---
