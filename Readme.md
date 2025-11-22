🤖 **OCP Agentic AI Self-Healing Project**

This project implements an Agentic AI workflow on OpenShift to provide self-healing capabilities.
It uses a multi-agent system — **Diagnosis, Remediation, and Reflection** — to analyze Prometheus alerts, propose solutions via Llama 3, and execute fixes (like restarting pods) after human approval via Slack.

This guide provides the steps to deploy and configure the agents on your OpenShift cluster.

---

## 🧩 Prerequisites

Before you begin, make sure you have:

✅ An OpenShift project — preconfigured for: **vigneshbaskar-dev**
💬 A Slack channel — preconfigured for: **#openshift-alerts**
🧰 Installed CLI tools:

* `oc` (OpenShift CLI)
* `git`

---

## ⚙️ Step 1: Get API Keys & Tokens

You will need two secret keys to run this project.

### **1A. Get Your Groq (Llama) API Key**

We use Groq for free, high-speed access to the Llama 3 model.

1. Go to [https://groq.com](https://groq.com) and sign up for a free account.
2. Click your account → **API Keys** → **Create API Key**.
3. Name it (e.g. `openshift-agent`) → click **Create**.
4. Copy the key (starts with `gsk_...`).

You’ll use this in **Step 3**.

---

### **1B. Get Your Slack Bot Token**

You’ll create a Slack App to act as your bot.

1. Go to [https://api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**.
2. Name your app (e.g. *OpenShift Agent*) → select your test workspace.
3. In the left sidebar, go to **OAuth & Permissions**.
4. Under **Bot Token Scopes**, add:

   * `chat:write`
   * `chat:write.public`
5. Click **Install to Workspace** → **Allow**.
6. Copy your **Bot User OAuth Token** (starts with `xoxb_...`).

You’ll use this in **Step 3**.

Finally, in Slack run:

```
/invite @OpenShift Agent
```

(or whatever you named your bot).

---

## 🚨 Step 2: Configure Alertmanager

This step updates Alertmanager to send all alerts to your new AI agent.

Update your **alert-manager-config.yml** (found in the repo root) with the following content:

```
global:
  resolve_timeout: 5m

route:
  group_by: ['alertname']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 1h
  receiver: 'ai_diagnostics'

receivers:
  - name: 'ai_diagnostics'
    webhook_configs:
      - url: 'http://diagnosis-agent-svc:8080/alert'
        send_resolved: true

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

Apply the configuration to your cluster:

```
oc create configmap alertmanager-main \
  --from-file=alertmanager.yml=alert-manager-config.yml \
  -o yaml --dry-run=client | oc replace -f -
```

The Alertmanager pod will automatically reload the new configuration.

---

## 🔐 Step 3: Create Secrets and ConfigMaps

Use the keys you generated in Step 1 to create the Kubernetes secrets.

```
oc create secret generic ai-secrets \
  --from-literal=GROQ_API_KEY='gsk_YOUR_KEY_HERE' \
  --from-literal=SLACK_BOT_TOKEN='xoxb_YOUR_TOKEN_HERE'

oc create configmap agent-config \
  --from-literal=SLACK_CHANNEL='#openshift-alerts'
```

---

## 🚀 Step 4: Build and Deploy Agents

Build and deploy all three agents. The **kubernetes.yaml** files are already preconfigured for the project: `vigneshbaskar-dev`.

### **Diagnosis Agent**

```
cd agents/diagnosis-agent
oc new-build --name=diagnosis-agent --binary --strategy=docker
oc start-build diagnosis-agent --from-dir=. --follow --no-cache
oc apply -f kubernetes.yaml
cd ../..
```

### **Remediation Agent**

```
cd agents/remediation-agent
oc new-build --name=remediation-agent --binary --strategy=docker
oc start-build remediation-agent --from-dir=. --follow
oc apply -f kubernetes.yaml
cd ../..
```

### **Reflection Agent**

```
cd agents/reflection-agent
oc new-build --name=reflection-agent --binary --strategy=docker
oc start-build reflection-agent --from-dir=. --follow
oc apply -f kubernetes.yaml
cd ../..
```

### Grant Permissions

Give the agents permission to delete pods (for restarting):

```
oc adm policy add-role-to-user edit -z default -n vigneshbaskar-dev
```

---

## 💬 Step 5: Configure Slack App for Interactivity (HTTPS)

Slack requires a Secure HTTPS URL to communicate with your cluster.

### Create a Secure Route:

Delete the old insecure route and create an Edge termination route.

```
oc delete route diagnosis-agent-svc --ignore-not-found
oc create route edge diagnosis-agent-https --service=diagnosis-agent-svc --port=8080
```

### Get the Route URL:

```
oc get route diagnosis-agent-https -o jsonpath='https://{.spec.host}/slack-interactive'
```

(Copy this output exactly.)

### Update Slack:

1. Go to your Slack App page (api.slack.com).
2. Go to **Interactivity & Shortcuts**.
3. Turn **Interactivity ON**.
4. Paste the URL from step 2 into the **Request URL** box.
5. Click **Save Changes**.

---

## 🧪 Manual Testing & Verification

You can test the entire AI workflow manually without waiting for Prometheus.

### **1. Get a Target Pod**

```
oc scale deployment deploy-one --replicas=1
export TARGET_POD=$(oc get pods -l app=deploy-one -o jsonpath='{.items[0].metadata.name}')
echo "Targeting Pod: $TARGET_POD"
```

### **2. Get Agent Public URL**

```
export AGENT_URL=$(oc get route diagnosis-agent-https -o jsonpath='{.spec.host}')
```

### **3. Send Fake Alert**

```
curl -X POST https://$AGENT_URL/alert \
     -H "Content-Type: application/json" \
     -d '{
           "status": "firing",
           "alerts": [
             {
               "commonLabels": {
                 "alertname": "HighCPUUsage",
                 "pod": "'$TARGET_POD'",
                 "namespace": "vigneshbaskar-dev"
               },
               "commonAnnotations": {
                 "summary": "Pod is consuming excessive CPU. Restart required."
               }
             }
           ]
         }'
```

### **4. Approve & Watch Magic**

Go to your **#openshift-alerts** channel in Slack.
You will see the AI analysis recommending a restart.
Click **Approve Remediation**.

Watch your terminal:

```
oc get pods -w
```

You will see the target pod **Terminating** and a new pod **ContainerCreating** instantly!

---

## ✅ System Ready!

🎉 Your system is now fully deployed!
