-- 对话消息的发言人（子 agent id）。空字符串代表历史遗留消息，界面按总管显示。
ALTER TABLE conversation_messages ADD COLUMN agent TEXT NOT NULL DEFAULT '';
