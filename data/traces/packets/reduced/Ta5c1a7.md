# Configuration packet (E1+E+T) Ta5c1a7

Record types present: R-A, R-E, R-T.
withheld: [R-U, R-P]

## Core
- problem: 3
- language: Python
- verdict: AC
- submission time: 0 min (all times are minutes relative to the submission; device and judge clocks are separate and uncalibrated)

### Submitted program
```
text = input()
count = 0
for w in text.split(' '):
    if w != '':
        count += 1
print(count)
```

## Assistant answers (R-A)

## Editor events and source captures (R-E)

- D1 at -0.2 min: insertion of 78 characters into main.py, version 79
```
text = input()
count = 0
for w in text.split(' '):
    if w != '':
        cou
```
- D2 at -0.2 min: insertion of 21 characters into main.py, version 100
```
nt += 1
print(count)

```
- save at -0.2 min: main.py

Source captures (state of the participant's files):
- capture at -0.5 min: best same-language file main.py, token similarity to the submitted program 0.000, identical: False
- capture at -0.2 min: best same-language file main.py, token similarity to the submitted program 1.000, identical: True
- capture at -0.2 min: best same-language file main.py, token similarity to the submitted program 1.000, identical: True

