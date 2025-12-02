# 🤖 OCP Agentic AI Self-Healing System

This project implements an autonomous Agentic AI workflow on OpenShift to provide self-healing capabilities.
It uses a multi-agent system — **Diagnosis, Remediation, and Reflection** — to monitor Prometheus alerts, analyze root causes using **Llama 3 (via Groq)**, and execute fixes (like restarting pods or scaling deployments) after human approval via Slack.

---

## 🧩 Prerequisites

Before you begin, ensure you have:

* ✅ **OpenShift Cluster:** Access to a project named `vigneshbaskar-dev`
* 💬 **Slack Workspace:** A channel named `#openshift-alerts`
* 🧰 **CLI Tools:** `oc` (OpenShift CLI) and `git` installed

---

## ⚙️ Step 1: Get API Keys & Tokens

You will need three secrets to run this project.

### 1. Groq (Llama 3) API Key

* Go to [https://groq.com](https://groq.com)
* Create an API Key
* Copy the key (starts with `gsk_...`)

### 2. Slack Bot Token

* Go to [https://api.slack.com/apps](https://api.slack.com/apps) → **Create New App**
* Go to **OAuth & Permissions**
* Add Scopes:

  * `chat:write`
  * `chat:write.public`
* Install to Workspace
* Copy the **Bot User OAuth Token** (starts with `xoxb_...`)

### 3. Slack Incoming Webhook URL

* In your Slack App settings, go to **Incoming Webhooks**
* Activate it
* Click **Add New Webhook to Workspace**
* Select channel: `#openshift-alerts`
* Copy the URL (starts with `https://hooks.slack.com/services/...`)

---

## 🔐 Step 2: Create Secrets & Configs

Run these commands to store your keys in the cluster:

```bash
# Create Secrets (Replace with your actual keys)
oc create secret generic ai-secrets \
  --from-literal=GROQ_API_KEY='gsk_YOUR_KEY_HERE' \
  --from-literal=SLACK_BOT_TOKEN='xoxb_YOUR_TOKEN_HERE'

# Create Global Config
oc create configmap agent-config \
  --from-literal=SLACK_CHANNEL='#openshift-alerts'
```

---

## 🚨 Step 3: Configure Alertmanager

This configuration routes alerts to both Slack (for visibility) and your AI Agent (for fixing).

Create a file named **alertmanager-config.yaml** with the content below.
**IMPORTANT:** Replace `YOUR_REAL_WEBHOOK_URL_HERE` with the URL from Step 1.3.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: alertmanager-config
  labels:
    name: alertmanager-config
data:
  alertmanager.yml: |
    global:
      resolve_timeout: 5m

    route:
      group_by: ['alertname']
      group_wait: 30s
      group_interval: 5m
      repeat_interval: 1h
      # Default receiver
      receiver: 'ai_diagnostics'
      
      # Routing Logic: Send to BOTH Slack and AI
      routes:
        - receiver: 'slack-notifications'
          match_re:
            alertname: '.*'
          continue: true
        - receiver: 'ai_diagnostics'
          match_re:
            alertname: '.*'

    receivers:
    - name: 'ai_diagnostics'
      webhook_configs:
      - url: 'http://diagnosis-agent-svc:8080/alert'
        send_resolved: true

    - name: 'slack-notifications'
      slack_configs:
      - api_url: '[https://hooks.slack.com/services/YOUR_REAL_WEBHOOK_URL_HERE](https://hooks.slack.com/services/YOUR_REAL_WEBHOOK_URL_HERE)'
        channel: '#openshift-alerts'
        send_resolved: true

    inhibit_rules:
    - source_match:
        severity: 'critical'
      target_match:
        severity: 'warning'
      equal: ['alertname', 'dev', 'instance']
```

Apply the configuration:

```bash
oc apply -f alertmanager-config.yaml
oc delete pod -l app=alertmanager  # Restart to load config
```

---

## 🚀 Step 4: Build and Deploy Agents

Deploy the three intelligent agents.

---

### 1. Diagnosis Agent

Analyzes alerts, checks logs, and proposes fixes.

```bash
cd agents/diagnosis-agent
oc new-build --name=diagnosis-agent --binary --strategy=docker
oc start-build diagnosis-agent --from-dir=. --follow --no-cache
oc apply -f kubernetes.yaml
cd ../..
```

---

### 2. Remediation Agent

Executes the fix (Restart Pod / Scale Deployment).

```bash
cd agents/remediation-agent
oc new-build --name=remediation-agent --binary --strategy=docker
oc start-build remediation-agent --from-dir=. --follow --no-cache
oc apply -f kubernetes.yaml
cd ../..
```

---

### 3. Reflection Agent

Verifies the fix was successful and reports back.

```bash
cd agents/reflection-agent
oc new-build --name=reflection-agent --binary --strategy=docker
oc start-build reflection-agent --from-dir=. --follow --no-cache
oc apply -f kubernetes.yaml
cd ../..
```

---

## 👮 Step 5: Grant Permissions

The agents need permission to modify resources in your namespace.

```bash
# Allow the remediation agent to delete pods and scale deployments
oc adm policy add-role-to-user edit -z remediation-agent-sa -n vigneshbaskar-dev
```

---

## 💬 Step 6: Configure Slack Interactivity

To allow the **“Approve Fix”** button to work, Slack needs a secure URL to talk back to your cluster.

---

### 1. Create Secure Route

```bash
# Delete old route if exists
oc delete route diagnosis-agent-https --ignore-not-found

# Create HTTPS Edge Route
oc create route edge diagnosis-agent-https --service=diagnosis-agent-svc --port=8080
```

---

### 2. Get the URL

```bash
oc get route diagnosis-agent-https -o jsonpath='https://{.spec.host}/slack-interactive'
```

Copy the output.

---

### 3. Update Slack App

* Go to your Slack App Dashboard
* Click **Interactivity & Shortcuts**
* Toggle **On**
* Paste the URL into **Request URL**
* Click **Save Changes**

---

## 🧪 Step 7: Live Test (Self-Healing)

### 1. Trigger the Failure

Scale a deployment to `0` to trigger the alert:

```bash
oc scale deployment deploy-one --replicas=0
```
