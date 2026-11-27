# Configuration packet (E1+E+T) Tb01ae9

Record types present: R-A, R-E, R-T.
withheld: [R-U, R-P]

## Core
- problem: 2
- language: Python
- verdict: AC
- submission time: 0 min (all times are minutes relative to the submission; device and judge clocks are separate and uncalibrated)

### Submitted program
```
n = int(input())
nums = input().split()
nums.reverse()
print(' '.join(nums))
```

## Assistant answers (R-A)

### Answer to Q1 (this problem) at -0.2 min
```text

```

#### Q1.proposal1
```text
nums.reverse()
print(' '.join(nums))
```

## Editor events and source captures (R-E)

- D1 at -1.0 min: insertion of 62 characters into main.py, version 63
```
n = int(input())
nums = input().split()
print(' '.join(nums))

```
- save at -1.0 min: main.py
- D2 at -0.2 min: insertion of 15 characters into main.py, version 64
```
nums.reverse()

```
- save at -0.2 min: main.py

Source captures (state of the participant's files):
- capture at -1.2 min: best same-language file main.py, token similarity to the submitted program 0.000, identical: False
- capture at -1.0 min: best same-language file main.py, token similarity to the submitted program 0.915, identical: False
- capture at -0.9 min: best same-language file main.py, token similarity to the submitted program 0.915, identical: False
- capture at -0.2 min: best same-language file main.py, token similarity to the submitted program 0.915, identical: False
- capture at -0.2 min: best same-language file main.py, token similarity to the submitted program 1.000, identical: True
- capture at -0.2 min: best same-language file main.py, token similarity to the submitted program 1.000, identical: True

