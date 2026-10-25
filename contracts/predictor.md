# Predictor contract (A → B)

These are the two hand-offs that let A (training) and B (evaluation) work in parallel without sharing a session.

## 1. Validation logits file: `runs/<run>/val_logits.npz`
Written by A at the end of every training run, and for every frozen probe. B consumes it with no GPU and no model code.

| Array | dtype / shape | Meaning |
|---|---|---|
| `ids` | `str` `(N,)` | `service_request_id`, in the same order as the rows below |
| `logits` | `float32` `(N, 17)` | **Raw, uncalibrated** logits. Column `i` = `contracts/categories.json` → `classes[i]` |
| `labels` | `int64` `(N,)` | True class index |
| `run` | `str` scalar | run name (e.g. `siglip2b16-384-lpft-s13`) |
| `timm_name` | `str` scalar | backbone |

`N` must equal the number of rows in `data/val.csv` (4,252). B checks this.

## 2. Inference library: `ml/infer.py`
```python
from ml.infer import Predictor

p = Predictor.from_artifact("artifacts/<model_version>")   # reads model_meta.json + member_*.pt
p.meta                      # dict, validates against contracts/model_meta.schema.json
p.logits(["data/images/graffiti/123.jpg", ...])   # np.ndarray float32 (N, 17): raw logits (single member),
                                                  # or log of averaged member probs (ensemble)
p.probs(paths)              # calibrated probabilities: members' softmax probs averaged, then temperature on the log of the average
```
- Preprocessing is fully determined **per member** in `model_meta.json`: resize the short side, center-crop `img_size`, normalize with `mean`/`std`, **no padding**. Each ensemble member gets its own transform.
- It runs on CUDA if available, otherwise CPU. It batches internally.
- It must not read any split CSV. It only takes paths. (So `final_eval.py`, in B's lane, is the only place test paths come from.)

## 3. Artifact folder: `artifacts/<model_version>/` (gitignored, copied out of band)
```
model_meta.json      # contracts/model_meta.schema.json; A writes temperature/abstain_threshold as null,
                     # then B's eval/calibrate.py fills them in from val
member_0.pt          # state_dict; more members = an ensemble (probabilities averaged)
```
