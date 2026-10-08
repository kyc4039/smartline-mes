"""설비 보전 AI 분류기 — web 폴더 안에서 단독으로 동작하는 판정 전용 코드 (10/07)

학습 폴더(EM_model)의 src/predict.py · predictors.py · common.py 에서 '판정에 필요한 부분만' 옮겨 왔다.
판정 결과는 학습 폴더의 predict.classify()와 똑같다 (tools/export_maint_model.py 가 확인).

모델 위치: web/model_files/maintenance/   (config.py MAINT_MODEL_DIR 로 바꿀 수 있음)
  v5_final.json                 최종 조합 비중 (baseline 0.25 · bilstm 0.25 · klue 0.5)
  v5_baseline/baseline.joblib   TF-IDF + 로지스틱 회귀
  v5_bilstm/bilstm.keras, meta.json
  v5_klue/model.pt, meta.json, 토크나이저 파일, config.json(KLUE 구조 → 인터넷 · 허깅페이스 캐시 없이 동작)
처음 한 번 학습 폴더에서 복사:  cd D:\\EM_model ; uv run python web/tools/export_maint_model.py

학습 폴더와 달라진 점 (결과는 같음)
  - 작업 폴더를 바꾸지 않음 (예전: os.chdir(EM_model) → 그 사이 다른 스레드의 파일 경로가 틀어질 수 있었음)
  - KLUE: config.json이 있으면 구조만 만들고 학습한 가중치(model.pt)를 바로 넣음
          (예전: 사전학습 가중치 440MB를 먼저 읽은 뒤 덮어씀 → 더 느리고, 캐시 없으면 인터넷 필요)
"""
import json
import os
import re
import sys
import time
import types
import numpy as np
import config

MODELS = getattr(config, "MAINT_MODEL_DIR", None) or os.path.join(config.MODEL_DIR, "maintenance")

TYPES = ["기계", "전기", "유압공압", "센서"]
URGS = ["상", "중", "하"]
URG_NAME = {"상": "즉시", "중": "당일", "하": "정기"}
TYPE_NAME = {"기계": "기계 정비", "전기": "전기·제어", "유압공압": "유공압", "센서": "센서·계측"}

DANGER_WORDS = ["연기", "불꽃", "불똥", "타는 냄새", "탄내", "감전", "스파크", "누전", "화재",
                "폭발", "침수", "젖었", "물이 떨어", "물 떨어", "터졌", "터진", "협착", "끼임", "끼였"]
LOW_CONF = 0.5
MIN_LEN = 5
COLLAB_GAP = 0.15
HEDGE = re.compile(r"\?|것 ?같[은아다]|인지 ?모르|모르겠|봐 ?주세요|봐줘|해야 ?하나|불러 ?줘|없나|어떡|어떻게 ?해")

INFO = {"dir": MODELS, "models": {}, "load_sec": None, "klue_offline": None}

_kiwi = None


def tokenize(text):
    """형태소 단위로 자르기 (문장부호만 제거) — 학습 때와 똑같아야 함"""
    global _kiwi
    if _kiwi is None:
        from kiwipiepy import Kiwi
        _kiwi = Kiwi()
    return [t.form for t in _kiwi.tokenize(str(text))
            if not (t.tag.startswith("S") and t.tag not in ("SL", "SN", "SH"))]


def available():
    """web 폴더 모델을 써도 되나: 복사 + 결과 일치 확인(VERIFIED.txt)까지 끝났을 때만
    (확인 없이 강제로 쓰려면 config.py MAINT_USE_WEB = True)"""
    if not os.path.exists(os.path.join(MODELS, "v5_final.json")):
        return False
    return os.path.exists(os.path.join(MODELS, "VERIFIED.txt")) or bool(getattr(config, "MAINT_USE_WEB", False))


# ---------------------------------------------------------------- 모델별 로더 (predictors.py와 같은 계산)
def _sklearn_proba(m, texts, labels):
    p = m.predict_proba(texts)
    return p[:, [list(m.classes_).index(l) for l in labels]]


def _baseline(path):
    import joblib
    # baseline.joblib 안의 TF-IDF가 학습 코드의 common.tokenize 를 가리키고 있어서,
    # 학습 폴더 없이 불러오려면 'common'이라는 이름으로 tokenize를 잠깐 빌려 준다
    if "common" not in sys.modules or not hasattr(sys.modules["common"], "tokenize"):
        shim = types.ModuleType("common")
        shim.tokenize = tokenize
        sys.modules["common"] = shim
    m = joblib.load(path)
    return lambda texts: (_sklearn_proba(m["type"], texts, TYPES), _sklearn_proba(m["urgency"], texts, URGS))


def _bilstm(model_path, meta_path):
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")          # 텐서플로 경고 줄이기
    from tensorflow import keras
    model = keras.models.load_model(model_path)
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    two_way = meta.get("input") == "two_way_prepad"

    def f(texts):
        n, L = len(texts), meta["max_len"]
        fwd, bwd = np.zeros((n, L), dtype="int32"), np.zeros((n, L), dtype="int32")
        for i, t in enumerate(texts):
            ids = [meta["vocab"].get(w, 1) for w in tokenize(t)][:L]
            if not ids:
                continue
            if two_way:
                fwd[i, -len(ids):] = ids
                bwd[i, -len(ids):] = ids[::-1]
            else:
                fwd[i, :len(ids)] = ids
        pt, pu = model.predict([fwd, bwd] if two_way else fwd, verbose=0)
        return pt, pu
    return f


def _klue(d):
    import torch
    from torch import nn
    from transformers import AutoTokenizer, AutoModel, AutoConfig
    with open(os.path.join(d, "meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    offline = os.path.exists(os.path.join(d, "config.json"))
    INFO["klue_offline"] = offline

    class MultiHead(nn.Module):
        def __init__(self):
            super().__init__()
            if offline:      # 구조만 (가중치는 아래 model.pt로 전부 채움)
                self.encoder = AutoModel.from_config(AutoConfig.from_pretrained(d))
            else:            # 예전 방식: 허깅페이스 캐시(없으면 인터넷)에서 사전학습 모델
                self.encoder = AutoModel.from_pretrained(meta["model_name"])
            h = self.encoder.config.hidden_size
            self.drop = nn.Dropout(0.1)
            self.type_head, self.urg_head = nn.Linear(h, len(TYPES)), nn.Linear(h, len(URGS))

        def forward(self, ids, mask):
            cls = self.drop(self.encoder(input_ids=ids, attention_mask=mask).last_hidden_state[:, 0])
            return self.type_head(cls), self.urg_head(cls)

    tok = AutoTokenizer.from_pretrained(d)
    model = MultiHead()
    sd = torch.load(os.path.join(d, "model.pt"), map_location="cpu")
    missing, unexpected = model.load_state_dict(sd, strict=False)
    real_missing = [k for k in missing if not k.endswith("position_ids")]   # 버전에 따라 없는 버퍼는 무시
    unexpected = [k for k in unexpected if not k.endswith("position_ids")]
    if real_missing or unexpected:
        raise RuntimeError(f"KLUE 가중치가 구조와 안 맞음: 빠짐 {real_missing[:3]} · 남음 {list(unexpected)[:3]}")
    model.eval()

    @torch.no_grad()
    def f(texts):
        pt, pu = [], []
        for i in range(0, len(texts), 64):
            enc = tok(texts[i:i + 64], padding=True, truncation=True, max_length=meta["max_len"], return_tensors="pt")
            a, b = model(enc["input_ids"], enc["attention_mask"])
            pt.append(a.softmax(-1).numpy())
            pu.append(b.softmax(-1).numpy())
        return np.concatenate(pt), np.concatenate(pu)
    return f


# ---------------------------------------------------------------- 불러오기 · 판정 (predict.py와 같은 규칙)
_models, WEIGHTS = None, None


def load():
    global _models, WEIGHTS
    if _models is not None:
        return
    t0 = time.time()
    with open(os.path.join(MODELS, "v5_final.json"), encoding="utf-8") as f:
        WEIGHTS = {k: v for k, v in json.load(f)["weights"].items() if v > 0}
    out = {}
    loaders = {   # 비중이 0인 모델은 불러오지 않음 (지금 v5는 셋 다 씀)
        "baseline": lambda: _baseline(os.path.join(MODELS, "v5_baseline", "baseline.joblib")),
        "bilstm": lambda: _bilstm(os.path.join(MODELS, "v5_bilstm", "bilstm.keras"), os.path.join(MODELS, "v5_bilstm", "meta.json")),
        "klue": lambda: _klue(os.path.join(MODELS, "v5_klue")),
    }
    for k in WEIGHTS:
        t = time.time()
        out[k] = loaders[k]()
        INFO["models"][k] = {"weight": WEIGHTS[k], "sec": round(time.time() - t, 1)}
    _models = out
    INFO["load_sec"] = round(time.time() - t0, 1)


def _probs(texts):
    texts = [str(t).strip() for t in texts]
    res = {k: _models[k](texts) for k in WEIGHTS}
    pt = sum(w * res[k][0] for k, w in WEIGHTS.items())
    pu = sum(w * res[k][1] for k, w in WEIGHTS.items())
    return pt, pu


def _decide(text, pt, pu):
    text = str(text).strip()
    t_order = np.argsort(pt)[::-1]
    urgency = URGS[int(pu.argmax())]
    danger = urgency != "상" and any(w in text for w in DANGER_WORDS)
    if danger:
        urgency = "상"
    reasons = []
    if min(pt.max(), pu.max()) < LOW_CONF:
        reasons.append("확신도 낮음")
    if len(text) < MIN_LEN:
        reasons.append("문장이 짧음")
    if HEDGE.search(text):
        reasons.append("추측·질문·요청 표현")
    second = TYPES[int(t_order[1])]
    collab = second if pt[t_order[0]] - pt[t_order[1]] < COLLAB_GAP else None
    return {
        "type": TYPES[int(t_order[0])],
        "type_name": TYPE_NAME[TYPES[int(t_order[0])]],
        "type_probs": {t: round(float(p), 3) for t, p in zip(TYPES, pt)},
        "urgency": urgency,
        "urgency_name": URG_NAME[urgency] + " 조치" if urgency != "하" else "정기 점검",
        "urgency_probs": {URG_NAME[u]: round(float(p), 3) for u, p in zip(URGS, pu)},
        "danger_rule_applied": danger,
        "need_review": bool(reasons),
        "review_reasons": reasons,
        "collab": TYPE_NAME[collab] if collab else None,
    }


def classify(text):
    load()
    pt, pu = _probs([text])
    return _decide(text, pt[0], pu[0])


SAMPLES = ["프레스 내려올 때 끼익 소리 계속 남", "제어반에서 타는 냄새 나요 빨리 와주세요",
           "로봇 적재기에서 이상한 소리 들리는데, 이거 점검해야하나?", "소음"]


def line(t, r):
    """학습 폴더 predict.py 의 출력과 같은 모양 (export 도구가 두 결과를 글자 그대로 비교)"""
    flag = f" [확인 필요: {', '.join(r['review_reasons'])}]" if r["need_review"] else ""
    collab = f" (협업: {r['collab']})" if r["collab"] else ""
    return f"{t}\n  → {r['type_name']}{collab} / {r['urgency_name']}{flag}  {r['urgency_probs']}"
