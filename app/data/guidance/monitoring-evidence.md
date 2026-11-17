---
title: Showing model monitoring and drift awareness
source: Written for ResumeFit by the project author; original text, free to reuse in this project
version: 1
---
Monitoring means checking that a deployed model keeps behaving as it did when you tested it. Drift means the incoming data, or the model's outputs, have shifted away from what you saw before.

Simple, real ways to gain this experience: log each prediction's score, latency and model version; compare this week's score distribution with a baseline week using the mean and a statistical test such as Kolmogorov-Smirnov; track error rate and response time; collect user ratings and watch the average.

A truthful resume line: "Logged per-request latency and score; added a weekly check that flags a shift in the score distribution." You do not need a large system. Being able to explain what you would watch, and why, already answers most entry-level interview questions on monitoring.
