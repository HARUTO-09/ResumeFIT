---
title: Describing how you evaluated a machine learning model
source: Written for ResumeFit by the project author; original text, free to reuse in this project
version: 1
---
Interviewers trust a model result only when they know how it was measured. For each ML project, be able to state: the dataset and its size; how you split it into training, validation and test sets; the metric and why it suits the problem; the baseline you compared against; and the result on data the model never saw during training or tuning.

Accuracy alone can mislead on imbalanced data, so give precision, recall or F1 where classes are uneven. Say what went wrong too: where the model fails and what you would try next.

On the resume this fits in one line: "F1 0.83 on a held-out test set, against 0.71 for a logistic regression baseline." If your test set is small, say so.
