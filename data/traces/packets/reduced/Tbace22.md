# Configuration packet (E1+E+T) Tbace22

Record types present: R-A, R-E, R-T.
withheld: [R-U, R-P]

## Core
- problem: 2
- language: Python
- verdict: AC
- submission time: 0 min (all times are minutes relative to the submission; device and judge clocks are separate and uncalibrated)

### Submitted program
```
left_val = int(input())
right_val = input().split()
print(' '.join(right_val[::-1]))
```

## Assistant answers (R-A)

### Answer to Q1 (this problem) at -0.5 min
```text

```

#### Q1.proposal1
```text
print(' '.join(nums[::-1]))
```

## Editor events and source captures (R-E)

- D1 at -1.3 min: insertion of 62 characters into main.py, version 63
```
n = int(input())
nums = input().split()
print(' '.join(nums))

```
- save at -1.3 min: main.py
- D2 at -0.5 min: insertion of 27 characters into main.py, version 64
```
print(' '.join(nums[::-1]))
```
- save at -0.5 min: main.py
- D3 at -0.3 min: insertion of 8 characters into main.py, version 65
```
left_val
```
- D4 at -0.2 min: insertion of 18 characters into main.py, version 66
```
right_valright_val
```
- save at -0.2 min: main.py

Source captures (state of the participant's files):
- capture at -1.5 min: best same-language file main.py, token similarity to the submitted program 0.000, identical: False
- capture at -1.3 min: best same-language file main.py, token similarity to the submitted program 0.800, identical: False
- capture at -1.2 min: best same-language file main.py, token similarity to the submitted program 0.800, identical: False
- capture at -0.5 min: best same-language file main.py, token similarity to the submitted program 0.800, identical: False
- capture at -0.5 min: best same-language file main.py, token similarity to the submitted program 0.909, identical: False
- capture at -0.5 min: best same-language file main.py, token similarity to the submitted program 0.909, identical: False
- capture at -0.2 min: best same-language file main.py, token similarity to the submitted program 1.000, identical: True

