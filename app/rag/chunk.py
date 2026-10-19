from dataclasses import dataclass


@dataclass
class ChunkDraft:
    category: str
    questions: str
    answer: str
    section_path: str | None
    content_type: str
    is_key_clause: bool


def _heading_level(line: str) -> tuple[int, str] | None:
    """返回 (层级, 标题)；仅 ## 与 ### 参与切分，H1(# )作文档标题忽略。"""
    if line.startswith("### "):
        return 3, line[4:].strip()
    if line.startswith("## "):
        return 2, line[3:].strip()
    return None


def split_policy_markdown(md_text: str, *, content_type: str, root_category: str) -> list[ChunkDraft]:
    # 1) 按标题切段：[(level, title, body_lines)]，正文与前置 blockquote 自然留在段外被丢弃
    lines = md_text.splitlines()
    sections: list[tuple[int, str, list[str]]] = []
    current: tuple[int, str, list[str]] | None = None
    for line in lines:
        heading = _heading_level(line)
        if heading is not None:
            if current is not None:
                sections.append(current)
            current = (heading[0], heading[1], [])
        elif current is not None:
            current[2].append(line)
    if current is not None:
        sections.append(current)

    # 2) 判定每个 ## 段是「章」还是「平铺条款」：紧跟其后的段是 ### 即为章
    has_child = [False] * len(sections)
    for i in range(len(sections) - 1):
        if sections[i][0] == 2 and sections[i + 1][0] == 3:
            has_child[i] = True

    # 3) 生成 chunk
    chunks: list[ChunkDraft] = []
    chapter_title: str | None = None
    for i, (level, title, body) in enumerate(sections):
        body_text = "\n".join(body).strip()
        if level == 2:
            if has_child[i]:
                # 章：仅作分组路径；若有正文（章节导语）单独成块
                chapter_title = title
                if body_text:
                    chunks.append(ChunkDraft(
                        category=root_category, questions=title, answer=body_text,
                        section_path=f"{root_category} > {title}",
                        content_type=content_type,
                        is_key_clause=("【" in title and "】" in title),
                    ))
                continue
            # 平铺条款（无 ### 子项）
            chapter_title = None
            if not body_text:
                continue
            chunks.append(ChunkDraft(
                category=root_category, questions=title, answer=body_text,
                section_path=f"{root_category} > {title}",
                content_type=content_type,
                is_key_clause=("【" in title and "】" in title),
            ))
        else:  # level == 3
            if not body_text:
                continue
            cat = f"{root_category} > {chapter_title}" if chapter_title else root_category
            sp = f"{root_category} > {chapter_title} > {title}" if chapter_title else f"{root_category} > {title}"
            chunks.append(ChunkDraft(
                category=cat, questions=title, answer=body_text, section_path=sp,
                content_type=content_type,
                is_key_clause=("【" in title and "】" in title),
            ))
    return chunks
