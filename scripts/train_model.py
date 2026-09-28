"""Train a local Russian issue classifier on requests_6000.jsonl."""

from collections import Counter
import json
from pathlib import Path
import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, f1_score
from sklearn.pipeline import FeatureUnion, Pipeline

HERE = Path(__file__).resolve().parents[1] / "data"
DATA = HERE / "requests_6000.jsonl"
MODEL = HERE / "issue_model.joblib"
METRICS = HERE / "metrics.json"

rows = [json.loads(line) for line in DATA.open(encoding="utf-8")]
train = [r for r in rows if r["split"] == "train"]
validation = [r for r in rows if r["split"] == "validation"]
test = [r for r in rows if r["split"] == "test"]

model = Pipeline([
    ("features", FeatureUnion([
        ("word", TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True, max_features=30000)),
        ("char", TfidfVectorizer(analyzer="char", ngram_range=(3, 5), min_df=2, sublinear_tf=True, max_features=45000)),
    ])),
    ("classifier", LogisticRegression(max_iter=700, class_weight="balanced")),
])
model.fit([r["text_ru"] for r in train], [r["category"] for r in train])

def evaluate(part):
    gold = [r["category"] for r in part]
    predicted = model.predict([r["text_ru"] for r in part])
    return {
        "rows": len(part),
        "accuracy": round(accuracy_score(gold, predicted), 4),
        "macro_f1": round(f1_score(gold, predicted, average="macro"), 4),
        "report": classification_report(gold, predicted, output_dict=True, zero_division=0),
    }

metrics = {
    "meaning": "Scores measure held-out synthetic Moscow seed phrases only. They do not estimate accuracy on real resident messages or routing correctness.",
    "train_rows": len(train),
    "validation": evaluate(validation),
    "test": evaluate(test),
    "class_counts": dict(Counter(r["category"] for r in rows)),
}
joblib.dump(model, MODEL, compress=3)
METRICS.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Saved {MODEL.name}; validation macro-F1={metrics['validation']['macro_f1']}; synthetic test macro-F1={metrics['test']['macro_f1']}")
