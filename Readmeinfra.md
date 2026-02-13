# 🤖 OCP Agentic AI Self-Healing System

This project implements an autonomous Agentic AI workflow on OpenShift to provide self-healing capabilities. It uses a multi-agent system — **Diagnosis, Remediation, and Reflection** — to monitor Prometheus alerts, analyze root causes, and execute fixes (like restarting pods or scaling deployments) after human approval via Slack.

---

## 🧩 Prerequisites

Before you begin, ensure you have:

- ✅ **OpenShift Cluster**: Access to a project named `vigneshbaskar-dev`
- 💬 **Slack Workspace**: A channel for alerts (if using AI agents for notifications)
- 🐙 **oc CLI**: Installed and logged in

---

## 🚀 Deployment Instructions

All infra YAML files are located in the `infra/` directory:


