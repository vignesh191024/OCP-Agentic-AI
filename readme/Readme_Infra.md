# 🏗️ OpenShift Infrastructure with Integrated Monitoring

This project provides a ready-to-deploy Sample app and monitoring tool on OpenShift. 

It sets up:

- **Sample Applications (Deploy One & Deploy Two)**: To demonstrate dynamic monitoring
- **Prometheus**: For metrics collection and monitoring
- **Alertmanager**: For handling alerts from Prometheus

This setup is namespace-aware and can be reused in any OpenShift project with minimal changes (only the namespace needs to be updated).

---

## 🧩 Prerequisites

Before you begin, ensure you have:

- ✅ **OpenShift Cluster**: Access to a project namespace
- 🐙 **oc CLI**: Installed and logged in

---

## 🚀 Deployment Instructions

All infrastructure YAML files are located in the `infra/` directory:

infra/
├── alertmanager-complete.yaml
├── prometheus-complete.yaml
├── deploy1-deployment.yaml
└── deploy2-deployment.yaml

---

1️⃣ Switch to Your Project / Namespace

```bash
oc project <namespace>

---

2️⃣ Deploy Alertmanager

```bash
oc apply -f infra/alertmanager-complete.yaml

Verify Deployment:

```bash
oc get pods -n <namespace>
oc get svc -n <namespace>
oc get route -n <namespace>

3️⃣ Deploy Prometheus

```bash
oc apply -f infra/prometheus-complete.yaml

Verify Deployment:

```bash
oc get pods -n <namespace>
oc get svc -n <namespace>
oc get route -n <namespace>

4️⃣ Access the Prometheus UI and Alertmanager UI via the Route in web:

```bash
oc get route

copy the Prometheus route and access the web interface via https://<route-URL>
copy the Alertmanager route and access the web interface via https://<route-URL>

note: if https:// fails try with http://

5️⃣ Deploy Sample Applications

--Deploy One

```bash
oc apply -f infra/deploy1-deployment.yaml

--Deploy Two

```bash
oc apply -f infra/deploy2-deployment.yaml

Verify Pods and Services:

```bash
oc get pods -n <namespace>
oc get svc -n <namespace>

5️⃣ Check Prometheus Targets



