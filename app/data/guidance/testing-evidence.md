---
title: Showing testing and code quality
source: Written for ResumeFit by the project author; original text, free to reuse in this project
version: 1
---
Many student resumes never mention testing, so a truthful line about it stands out, especially for roles that list "functional testing" or "quality".

What you can do in a weekend: write unit tests with pytest for the core functions of one project; add tests for invalid input and error paths; measure coverage; run the tests automatically on every push with a free continuous integration service.

Then state it plainly: "Wrote 40 pytest tests covering parsing and scoring; 85% line coverage; tests run in CI on every commit." For machine learning projects, also describe how you evaluated the model: held-out data, a baseline, and a check that fails when quality drops. Be ready to describe one bug your tests caught.
