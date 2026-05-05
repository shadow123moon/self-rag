# services/rag_service.py
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI
from config import settings
from services.search_service import  hybrid_search
from services.history_service import get_history_messages, save_chat_turn

from services.rerank_service import rerank_service
import logging
logger = logging.getLogger(__name__)

class RagService:
    def __init__(self):
        self.chat_model = ChatOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            model=settings.OPENAI_MODEL,
        )
        self.rewrite_model = ChatOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            model=settings.OPENAI_MODEL,
            temperature=0,  # ← 必须 0
        )
        self.prompt_template = ChatPromptTemplate.from_messages([
            ("system", "以我提供的已知参考资料为主，简洁和专业的回答用户的问题。参考资料：{context}"),
            MessagesPlaceholder("history"),
            ("user", "请回答用户提问：{input}")
        ])
        self.base_chain = self.__get_Basechain()


    def __get_Basechain(self):
        return self.prompt_template | self.chat_model | StrOutputParser()



    @staticmethod
    def _format_context(docs_with_scores: list[tuple[Any, float]]) -> str:
        if not docs_with_scores:
            return "无相关资料"

        formatted = ""
        for doc, _ in docs_with_scores:
            formatted += f"文档片段：{doc.page_content}\n文档元数据：{doc.metadata}\n\n"
        return formatted

    @staticmethod
    def _build_references(docs_with_scores: list[tuple[Any, float]]) -> list[dict]:
        references = []
        for i, (doc, score) in enumerate(docs_with_scores, start=1):
            meta = doc.metadata
            references.append({
                "index": i,
                "document_id": meta.get("document_id", ""),
                "filename": meta.get("filename", ""),
                "page": meta.get("page_number"),
                "content": doc.page_content[:200],
            })
        return references
    def rewrite_query(self, query: str,history:list[BaseMessage]) :

        rewrite_prompt = """
        你是检索查询改写器，不是问答助手。
        
        你的任务：把用户当前问题改写成一句适合知识库检索的查询语句。
        
        严格规则：
        1. 只能输出一句查询语句。
        2. 不允许回答用户问题。
        3. 不允许输出建议、解释、编号、Markdown。
        4. 不允许说“资料中没有”。
        5. 如果当前问题是“重新回答/再说一遍/继续/详细点”，请根据最近一轮有效用户问题补全查询。
        6. 如果无法改写，原样输出用户当前问题。

        """
        prompt_template=ChatPromptTemplate.from_messages([
            ("system",rewrite_prompt),
            MessagesPlaceholder("history"),
            ("user", "用户提问：{input}")
        ])
        recent_history = history[-6:]  # 最近 3 轮（每轮 user+ai 共 2 条）

        chain=prompt_template | self.chat_model | StrOutputParser()
        bad_phrases = [
            "根据",
            "参考资料",
            "无法",
            "建议",
            "我无法",
            "我随时",
            "以下",
            "1.",
            "2.",
        ]

        try:
            rewritten = chain.invoke({"input": query, "history": recent_history})
            logger.info("query 改写: %r → %r", query, rewritten)
            rewritten = rewritten.strip()
            if not rewritten or len(rewritten) > 200:
                rewritten = query
            if "\n" in rewritten:
                rewritten = query

            if any(word in rewritten for word in bad_phrases):
                rewritten = query
            return rewritten

        except Exception as e:
            logger.warning("query 改写失败，使用原 query: %s", e)
            return query
    def stream_answer(
        self,
        query: str,
        user_id: str,
        session_id: str = "default",
        top_k: int = 5,
        save_history: bool = True,
    ):
        user_id = user_id or "default_user"
        session_id = session_id or "default"

        history = get_history_messages(user_id, session_id)
        if history:
            rewritten_query = self.rewrite_query(query, history)
        else:
            rewritten_query = query

        if settings.RERANK_ENABLED:
            docs_with_scores = rerank_service.hybrid_search_with_rerank(top_k=top_k,query=rewritten_query )
        else:
            docs_with_scores = hybrid_search(rewritten_query, top_k=top_k)

        context = self._format_context(docs_with_scores)
        references = self._build_references(docs_with_scores)

        payload = {
            "history": history,
            "context": context,
            "input": query,
        }

        full_answer = ""
        for token in self.base_chain.stream(payload):
            if not token:
                continue
            full_answer += token
            yield {
                "type": "chunk",
                "content": token,
            }

        if save_history:
            save_chat_turn(
                user_id=user_id,
                session_id=session_id,
                question=query,
                answer=full_answer,
                references=references,
            )

        yield {
            "type": "done",
            "answer": full_answer,
            "user_id": user_id,
            "session_id": session_id,
            "references": references,
        }
