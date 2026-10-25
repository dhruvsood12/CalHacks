# contracts/: the interfaces between A, B and C (frozen at G1, 19:30 PT)

Everyone builds against these from the start. B's stub API returns exactly these shapes, so C never waits on A and B never waits on A.

| File | Between | Meaning |
|---|---|---|
| `categories.json` | everyone | 17 classes. **`index` = model output index.** Includes display name, primary agency, the SoQL filter that defines the class, and the real-world volume/prior. |
| `classify.response.schema.json` | B → C | `POST /classify` (multipart field `image`) response: top-3 calibrated probabilities + `abstain` |
| `report.request.schema.json` | C → B | `POST /report` body: image (base64), the classification, language, location, note |
| `report.response.schema.json` | B → C | Claude's structured report: category check, text in the user's language + English, agency, next steps, `emergency` |
| `model_meta.schema.json` | A → B | Metadata next to `model.pt`: timm name, preprocessing, class order, temperature, abstain threshold, val metrics |
| `examples/*.json` | everyone | Valid examples. CI validates them against the schemas. |

`GET /health` → `{"status": "ok", "model_version": "<str>", "num_classes": 17}`

**Rules**
- Labels are always the `label` strings from `categories.json` (snake_case). Display text comes from `display_name`.
- `prob` values are calibrated (temperature-scaled) and sorted descending. `abstain` = `top_k[0].prob < abstain_threshold`.
- `/report` must never call any SF 311 write endpoint.
- **Changing anything here:** a `shared` PR, a 👍 from all three, examples updated, and CI green.
