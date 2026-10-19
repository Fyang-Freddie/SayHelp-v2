from app.rag.chunk import split_policy_markdown


FLAT_MD = """# 售后政策

> 版本：AS-2026.10

## A01【售后类型】
售后服务包括：补发、维修、换货、部分退款、退货退款、仅退款以及平台争议处理。

## A02【售后起算时间】
需要以收货为起点的服务，原则上以物流签收时间为依据。
"""

TWO_LEVEL_MD = """# 退款退货政策

## 第一章 基本定义

### R01【退款】
退款是指交易款项全部或部分退回买家。

### R02【退货退款】
退货退款是指买家将已收到的商品退回。
"""


def test_split_flat_clauses():
    chunks = split_policy_markdown(FLAT_MD, content_type="manual", root_category="售后政策")
    assert [c.questions for c in chunks] == ["A01【售后类型】", "A02【售后起算时间】"]
    assert chunks[0].answer.startswith("售后服务包括")
    assert chunks[0].section_path == "售后政策 > A01【售后类型】"
    assert chunks[0].category == "售后政策"
    assert chunks[0].content_type == "manual"
    assert chunks[0].is_key_clause is True


def test_split_two_level_chapter_path_in_category():
    chunks = split_policy_markdown(TWO_LEVEL_MD, content_type="policy", root_category="退款退货政策")
    # 章（无正文）不单独成块，只产生两个 R 条款
    assert [c.questions for c in chunks] == ["R01【退款】", "R02【退货退款】"]
    assert chunks[0].category == "退款退货政策 > 第一章 基本定义"
    assert chunks[0].section_path == "退款退货政策 > 第一章 基本定义 > R01【退款】"


def test_chapter_preamble_emits_own_chunk():
    md = "# 退款退货政策\n\n## 第一章 基本定义\n本章定义退款与退货退款两类基础概念。\n\n### R01【退款】\n退款是指款项退回。\n"
    chunks = split_policy_markdown(md, content_type="policy", root_category="退款退货政策")
    questions = [c.questions for c in chunks]
    assert "第一章 基本定义" in questions and "R01【退款】" in questions


def test_split_skips_front_matter_and_h1():
    md = "# 标题\n\n> 版本说明\n\n## A01【售后类型】\n正文。\n"
    chunks = split_policy_markdown(md, content_type="manual", root_category="售后政策")
    assert len(chunks) == 1
    assert chunks[0].questions == "A01【售后类型】"


def test_mid_document_h1_becomes_own_chunk():
    md = (
        "# 商品规格手册\n\n"
        "## 40. 宠物主粮（型号 MM-CATFOOD2K）\n参数说明。\n\n"
        "# 商品检索规则\n\n1. 规则一\n2. 规则二\n"
    )
    chunks = split_policy_markdown(md, content_type="manual", root_category="商品规格手册")
    questions = [c.questions for c in chunks]
    assert "40. 宠物主粮（型号 MM-CATFOOD2K）" in questions
    assert "商品检索规则" in questions
    pet = next(c for c in chunks if "宠物主粮" in c.questions)
    assert "商品检索规则" not in pet.answer and "规则一" not in pet.answer
    rule = next(c for c in chunks if c.questions == "商品检索规则")
    assert "规则一" in rule.answer
    assert rule.category == "商品规格手册"
    assert rule.section_path == "商品规格手册 > 商品检索规则"
