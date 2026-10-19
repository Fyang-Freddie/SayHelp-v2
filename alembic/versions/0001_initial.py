"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-19
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# 冻结的 MySQL DDL（由 Base.metadata 按依赖顺序编译，含中文 ENUM 字面量与
# ON DELETE SET NULL 外键）。review_queue / conversations 先于
# low_confidence_questions 创建；tool_audit_logs 无外键。
_TABLES_UP = [
    ('conversation_summaries',
     """CREATE TABLE conversation_summaries (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	conversation_id BIGINT NOT NULL, 
	seq INTEGER NOT NULL, 
	from_msg_id BIGINT NOT NULL, 
	upto_msg_id BIGINT NOT NULL, 
	content TEXT NOT NULL, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	CONSTRAINT uk_conv_seq UNIQUE (conversation_id, seq)
)"""),
    ('conversations',
     """CREATE TABLE conversations (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	user_id BIGINT NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	summary TEXT, 
	summary_upto_msg_id BIGINT, 
	layer1_from_msg_id BIGINT, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	updated_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id)
)"""),
    ('eval_runs',
     """CREATE TABLE eval_runs (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	triggered_by ENUM('定时','手动') NOT NULL, 
	dataset_size INTEGER NOT NULL, 
	eval_set VARCHAR(64), 
	config_json JSON, 
	model_version VARCHAR(64), 
	metrics JSON NOT NULL, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id)
)"""),
    ('faith_cases',
     """CREATE TABLE faith_cases (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	eval_id VARCHAR(16) NOT NULL, 
	bucket VARCHAR(24) NOT NULL, 
	query VARCHAR(512) NOT NULL, 
	strategy VARCHAR(24) NOT NULL, 
	answer TEXT NOT NULL, 
	reason TEXT NOT NULL, 
	citations JSON, 
	judge_model VARCHAR(64), 
	status ENUM('未解决','已解决','无需解决') NOT NULL, 
	seen_count INTEGER NOT NULL, 
	first_seen_at DATETIME NOT NULL DEFAULT now(), 
	last_seen_at DATETIME NOT NULL DEFAULT now(), 
	resolution VARCHAR(300), 
	resolved_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (eval_id)
)"""),
    ('knowledge_chunks',
     """CREATE TABLE knowledge_chunks (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	category VARCHAR(255) NOT NULL, 
	questions TEXT NOT NULL, 
	answer TEXT NOT NULL, 
	section_path VARCHAR(512), 
	content_type VARCHAR(32), 
	is_key_clause BOOL NOT NULL, 
	prev_chunk_id BIGINT, 
	next_chunk_id BIGINT, 
	vector_id VARCHAR(64), 
	vectorize_status ENUM('pending','done') NOT NULL, 
	doc_id VARCHAR(64), 
	doc_version VARCHAR(32), 
	doc_source VARCHAR(255), 
	created_at DATETIME NOT NULL DEFAULT now(), 
	updated_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(prev_chunk_id) REFERENCES knowledge_chunks (id) ON DELETE SET NULL, 
	FOREIGN KEY(next_chunk_id) REFERENCES knowledge_chunks (id) ON DELETE SET NULL
)"""),
    ('logistics',
     """CREATE TABLE logistics (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	order_no VARCHAR(32) NOT NULL, 
	item_ids VARCHAR(128) NOT NULL, 
	waybill_no VARCHAR(32) NOT NULL, 
	logistics_type VARCHAR(16) NOT NULL, 
	carrier VARCHAR(32) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	latest_time DATETIME NOT NULL, 
	is_latest BOOL NOT NULL, 
	trajectory VARCHAR(1024) NOT NULL, 
	PRIMARY KEY (id)
)"""),
    ('messages',
     """CREATE TABLE messages (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	conversation_id BIGINT NOT NULL, 
	`role` ENUM('user','assistant','tool','system') NOT NULL, 
	content TEXT NOT NULL, 
	tool_call_id VARCHAR(64), 
	tool_calls JSON, 
	citations JSON, 
	feedback JSON, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id)
)"""),
    ('orders',
     """CREATE TABLE orders (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	customer_id VARCHAR(16) NOT NULL, 
	order_no VARCHAR(32) NOT NULL, 
	item_id VARCHAR(32) NOT NULL, 
	product_name VARCHAR(128) NOT NULL, 
	model_spec VARCHAR(128), 
	quantity INTEGER NOT NULL, 
	paid_amount DECIMAL(10, 2) NOT NULL, 
	order_time DATETIME NOT NULL, 
	sign_time DATETIME, 
	order_status VARCHAR(32) NOT NULL, 
	after_sale_status VARCHAR(32) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (item_id)
)"""),
    ('products',
     """CREATE TABLE products (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	product_name VARCHAR(128) NOT NULL, 
	model VARCHAR(64) NOT NULL, 
	order_spec VARCHAR(128) NOT NULL, 
	product_type VARCHAR(64) NOT NULL, 
	seven_day_return VARCHAR(128) NOT NULL, 
	warranty VARCHAR(128) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (model)
)"""),
    ('qa_extraction_staging',
     """CREATE TABLE qa_extraction_staging (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	batch_no VARCHAR(64) NOT NULL, 
	source_ref VARCHAR(255), 
	question TEXT NOT NULL, 
	answer TEXT NOT NULL, 
	status ENUM('extracted','kept','discarded') NOT NULL, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id)
)"""),
    ('refund_reasons',
     """CREATE TABLE refund_reasons (
	code VARCHAR(64) NOT NULL, 
	display_name VARCHAR(64) NOT NULL, 
	PRIMARY KEY (code)
)"""),
    ('retrieval_snapshots',
     """CREATE TABLE retrieval_snapshots (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	conversation_id BIGINT NOT NULL, 
	user_message_id BIGINT NOT NULL, 
	answer_message_id BIGINT, 
	evidence JSON, 
	evidence_confidence DECIMAL(5, 4), 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id)
)"""),
    ('review_queue',
     """CREATE TABLE review_queue (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	normalized_question VARCHAR(512) NOT NULL, 
	ai_suggested_answer TEXT, 
	occurrence_count INTEGER NOT NULL, 
	review_status ENUM('待审','通过','驳回') NOT NULL, 
	approved_answer TEXT, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	updated_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id)
)"""),
    ('tickets',
     """CREATE TABLE tickets (
	ticket_no VARCHAR(32) NOT NULL, 
	conversation_id BIGINT NOT NULL, 
	description TEXT NOT NULL, 
	type VARCHAR(32) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	idempotency_key VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (ticket_no), 
	UNIQUE (idempotency_key)
)"""),
    ('tool_audit_logs',
     """CREATE TABLE tool_audit_logs (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	conversation_id BIGINT, 
	tool_call_id VARCHAR(64), 
	tool_name VARCHAR(128) NOT NULL, 
	tool_source ENUM('builtin','mcp') NOT NULL, 
	mcp_server VARCHAR(64), 
	arguments JSON, 
	result_summary TEXT, 
	status ENUM('成功','失败','超时','校验拦下','权限拒绝') NOT NULL, 
	error_message VARCHAR(512), 
	retry_count INTEGER NOT NULL, 
	duration_ms INTEGER, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id)
)"""),
    ('topic_classifications',
     """CREATE TABLE topic_classifications (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	low_confidence_question_id BIGINT NOT NULL, 
	labels JSON NOT NULL, 
	classified_at DATETIME NOT NULL DEFAULT now(), 
	model_version VARCHAR(64), 
	PRIMARY KEY (id)
)"""),
    ('users',
     """CREATE TABLE users (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	username VARCHAR(64) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	`role` ENUM('customer','agent','admin') NOT NULL, 
	customer_id VARCHAR(16), 
	display_name VARCHAR(64), 
	is_active BOOL NOT NULL, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	UNIQUE (username)
)"""),
    ('low_confidence_questions',
     """CREATE TABLE low_confidence_questions (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	conversation_id BIGINT, 
	raw_question TEXT NOT NULL, 
	source ENUM('retrieval_low_conf','self_check','user_feedback') NOT NULL, 
	reason TEXT, 
	retrieved_chunks JSON, 
	matched_review_id BIGINT, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(conversation_id) REFERENCES conversations (id), 
	FOREIGN KEY(matched_review_id) REFERENCES review_queue (id) ON DELETE SET NULL
)"""),
]


def upgrade() -> None:
    for _name, ddl in _TABLES_UP:
        op.execute(ddl)


def downgrade() -> None:
    for name in reversed([t[0] for t in _TABLES_UP]):
        op.execute(f"DROP TABLE {name}")
