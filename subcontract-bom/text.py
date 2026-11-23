"""rack.layout 进模型的文字：唯一来源（设计稿七 W1–W4、W6）。

★草案占位，未定稿。逐字文本以实验定，由调度定稿后替换本文件；定稿前不出包、不入册。
登记脚本（tools/make_registration.py）与执行体（layout.py）都只从这里取文字，别处不写进模型的句子。
"""

# W1 工具卡 description（引用写法那一句留空，待 v0.2.135 落地后按实验定的写法填入）
W1_CARD = "【W1 待定稿】"

# W2 各入参 description
W2_INPUTS = {
    "from_drawing": "【W2 from_drawing 待定稿】",
    "columns_read": "【W2 columns_read 待定稿】",
    "run_length": "【W2 run_length 待定稿】",
    "column_pitch": "【W2 column_pitch 待定稿】",
    "level_segments": "【W2 level_segments 待定稿】",
    "beam_clear": "【W2 beam_clear 待定稿】",
    "zones": "【W2 zones 待定稿】",
    "pallets": "【W2 pallets 待定稿】",
    "pallet_plan_a": "【W2 pallet_plan_a 待定稿】",
    "pallet_plan_b": "【W2 pallet_plan_b 待定稿】",
}

# W3 not_computed[].reason 的三类句式。占位符：{item} 出参名；{needs} 缺的入参名（顿号连接）；
#   {upstream} 没算出的上游出参名（顿号连接）；{formula} 算式；{operands} 各操作数“名=值”（顿号连接）
W3_MISSING = "【W3 缺入参 待定稿】{item}｜{needs}"
W3_UPSTREAM = "【W3 上游没算出 待定稿】{item}｜{upstream}"
W3_INVALID = "【W3 不成立 待定稿】{item}｜{formula}｜{operands}"

# W4 失败回执的说明（一项也算不出）。占位符：{details} 各项原因（分号连接）
W4_NOTHING = "【W4 待定稿】{details}"

# W6 类型 rack_layout_receipt 的 note / title
W6_TYPE_NOTE = "【W6 待定稿】"

# W4b 入参形状不对时的说明（签名之外由工具自己挡下的情形；引擎先按 input_schema 校验，通常到不了这里）。
#   占位符：{path} 出问题的位置
W4_SHAPE = "【W4b 入参形状 待定稿】{path}"

# W3 注：照读列数与总长、列距不自洽时，记在 steps 的列数一项里（不改结果）
W3_STEP_INCONSISTENT = "【W3 注 不自洽 待定稿】"

# W1b 能力卡的用例（capability.examples，3–5 条，TL-16：场景信息只出现在这里）与不做的事（capability.non_goals）
W1_EXAMPLES = [
    {"input": "【W1b 用例 1 待定稿】", "output": "【W1b 用例 1 输出 待定稿】"},
    {"input": "【W1b 用例 2 待定稿】", "output": "【W1b 用例 2 输出 待定稿】"},
    {"input": "【W1b 用例 3 待定稿】", "output": "【W1b 用例 3 输出 待定稿】"},
]
W1_NON_GOALS = []
