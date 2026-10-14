-- 思考模式（DeepSeek thinking）下模型的思维链文本。
-- 单独一列而不是塞进 input_json：它是模型输出，不是输入快照的一部分，
-- 仅供界面回看思考过程，不进入后续模型上下文。
ALTER TABLE conversation_messages ADD COLUMN reasoning TEXT NOT NULL DEFAULT '';
