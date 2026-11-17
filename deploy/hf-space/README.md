---
title: ResumeFit API
emoji: 📄
colorFrom: gray
colorTo: gray
sdk: docker
app_port: 8000
pinned: false
short_description: API behind ResumeFit, a resume and job description fit checker
---

# ResumeFit API

The API behind ResumeFit. It scores a resume against a job description and explains the
gaps; a coach answers follow-up questions with citations. Every endpoint except
`/health` and `/auth/config` needs a Firebase sign-in. API docs are at `/docs`.

Source and full documentation: https://github.com/HARUTO-09/ResumeFIT

This Space is deployed from that repository with `deploy/hf_space.py`; edit the code
there, not here. The score is a guide to improving a resume, not a hiring decision, and
it can be wrong.
