---
title: Showing deployment experience
source: Written for ResumeFit by the project author; original text, free to reuse in this project
version: 1
---
Deployment means other people or programs can use your model or app without running your notebook. You do not need a paid cloud account to show it.

Ways to earn real deployment experience from a project you already have: wrap the model in a small web API (for example FastAPI or Flask) with one prediction endpoint; package it in a Docker image so it runs the same on any machine; host it on a free tier and keep the link alive; add a health check and basic request logging.

On the resume, say what was deployed, how, and what it handled. Example: "Served the classifier behind a FastAPI endpoint in a Docker container; median response 120 ms on CPU." Only write a number you measured. If the project never left a notebook, do the wrapping work first, then add the line.
