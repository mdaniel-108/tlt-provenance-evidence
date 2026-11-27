# Reference packet (full record) Tdcf4f5

Record types present: R-A, R-U, R-P, R-E, R-T.
withheld: []

## Core
- problem: 2
- language: Python
- verdict: AC
- submission time: 0 min (all times are minutes relative to the submission; device and judge clocks are separate and uncalibrated)

### Submitted program
```
n = int(input())
items = list(map(int, input().split()))
out = []
for i in range(n - 1, -1, -1):
    out.append(str(items[i]))
print(' '.join(out))
```

## Assistant answers (R-A)

## User messages and attached files (R-U)

## Proposal events (R-P)

(no proposal events)

## Editor events and source captures (R-E)

- D1 at -0.3 min: insertion of 78 characters into main.py, version 79
```
n = int(input())
items = list(map(int, input().split()))
out = []
for i in ran
```
- D2 at -0.2 min: insertion of 70 characters into main.py, version 149
```
ge(n - 1, -1, -1):
    out.append(str(items[i]))
print(' '.join(out))

```
- save at -0.2 min: main.py

Source captures (state of the participant's files):
- capture at -0.6 min: best same-language file main.py, token similarity to the submitted program 0.000, identical: False
- capture at -0.2 min: best same-language file main.py, token similarity to the submitted program 0.919, identical: False
- capture at -0.2 min: best same-language file main.py, token similarity to the submitted program 1.000, identical: True

