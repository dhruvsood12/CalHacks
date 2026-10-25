# contracts/: the interfaces between A, B and C (frozen at G1, 20:00 PT)

Everyone builds against these from the start. A's stub API and C's in-app `MockAPI` (bundled `examples/`) return exactly these shapes, and B develops on synthetic logits. Nobody waits on anybody.

| File | Between | Meaning |
|---|---|---|
| `categories.json` | everyone | 17 classes. **`index` = model output index.** Includes display name, primary agency, the SoQL filter that defines the class, and the real-world volume/prior. |
| `classify.response.schema.json` | A (API) → C | `POST /classify` (multipart field `image`) response: top-3 calibrated probabilities + `abstain` |
| `report.request.schema.json` | C → A (API) → B's report writer | `POST /report` body: image (base64), the classification, language, location, note |
| `report.response.schema.json` | B's report writer → A (API) → C | Claude's structured report: category check, text in the user's language + English, agency, next steps, `emergency` |
| `model_meta.schema.json` | A → B | Artifact metadata: class order, and per-member backbone and preprocessing (a mixed ensemble has different input sizes and normalization). Temperature and abstain threshold are filled in by B on val. |
| `predictor.md` | A → B | `val_logits.npz` format and the `ml/infer.py` `Predictor` interface: how B evaluates A's models without sharing a session |
| `examples/*.json` | everyone | Valid examples. CI validates them against the schemas. |

`GET /health` → `{"status": "ok", "model_version": "<str>", "num_classes": 17}`

**Rules**
- Labels are always the `label` strings from `categories.json` (snake_case). Display text comes from `display_name`.
- `prob` values are calibrated (temperature-scaled) and sorted descending. `abstain` = `top_k[0].prob < abstain_threshold`.
- `/report` must never call any SF 311 write endpoint.
- **Changing anything here:** a `shared` PR, a 👍 from all three, examples updated, and CI green.
