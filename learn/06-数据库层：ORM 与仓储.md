# 06 · 数据库层：ORM 与仓储

> 目标：看懂 `db.py`、`models.py`、`repositories/` 这三块，理解「为什么用 ORM + 仓储访问数据库」。
> 对照文件：`app/storage/db.py`、`app/storage/models.py`、`app/storage/repositories/`、`scripts/init_db.py`。

---

## 1. 先回答：为什么不直接写 SQL？

直接写 SQL 的问题：SQL 分散在业务代码里，改表结构要到处找；结果是一堆 `dict`，没有类型检查，写错字段名不报错；业务代码和"怎么存数据"耦合。

**ORM（对象关系映射）** 让"表"对应"Python 类"、行对应对象、列对应属性，代码里操作对象，ORM 自动翻译成 SQL。

```python
# 直接 SQL（不推荐散落在业务里）
user = conn.execute("SELECT * FROM users WHERE username=%s", (name,))

# ORM（本项目的方式）
user = UserRepository(session).get_by_username(name)   # 返回 User 对象
user.nickname  # 直接访问属性
```

## 2. 读 `db.py`（四个关键东西）

```python
engine = create_engine(settings.database_url, ...)      # ① 连接池
SessionLocal = sessionmaker(bind=engine, ...)            # ② 造会话的"工厂"
Base = declarative_base()                                 # ③ ORM 模型基类
def get_session(): ...                                    # ④ FastAPI 依赖：每次请求一个会话
```

| 名字 | 通俗解释 |
|------|----------|
| `engine` | 和 MySQL 的连接管理（连接池，用完回收复用） |
| `SessionLocal` | 造会话的工厂。**会话 = 你读写数据库的"工作台"** |
| `Base` | 所有模型的父类。`models.py` 里的类都继承它，`create_all` 才知道要建哪些表 |
| `get_session` | 一个请求开一个会话，请求结束自动提交/回滚/关闭 |

> `pool_pre_ping=True`：每次取连接先 ping 一下，连接断了自动重建（生产经验）。
> `echo=(settings.app_env == "dev")`：dev 下打印 SQL，方便调试（上一节讲过）。

## 3. 读 `models.py`：一张表 = 一个类

拿最典型的 `Message`（消息表）来拆解：

```python
class Message(Base):
    __tablename__ = "messages"                          # ① 表名

    id: Mapped[int] = mapped_column(UID, primary_key=True, autoincrement=True)   # ② 主键
    conversation_id: Mapped[int] = mapped_column(UID, ForeignKey("conversations.id"), nullable=False)  # ③ 外键
    role: Mapped[str] = mapped_column(String(16), nullable=False)                # ④ 普通列 + 类型 + 约束
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_refs: Mapped[list | None] = mapped_column(JSON)                       # ⑤ JSON 列
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)  # ⑥ 默认值

    conversation: Mapped[Conversation] = relationship(back_populates="messages") # ⑦ 关系
```

| 术语 | 含义 | 本例 |
|------|------|------|
| 主键 | 唯一标识一行 | `id` |
| 外键 | 引用另一张表的行 | `conversation_id` → conversations.id |
| 约束 | 数据的规则 | `nullable=False` 不允许为空 |
| JSON 列 | 存结构化的数据 | `source_refs`（溯源引用数组） |
| 关系 | 让 ORM 知道表和表怎么关联 | 一条消息属于一个会话 |

> `default=utcnow`：不传时间时自动用当前 UTC 时间。**为什么存 UTC？** 统一一个时区标准，展示层再转本地，避免"8 小时时差"的经典 bug。

## 4. 全项目的 12 张表（看一眼就够，不必记）

`users` → `conversations` → `messages`（用户聊天）
`users` → `homework_submissions` → `grading_results`（批改）
`users` → `mistakes` → `knowledge_points`（错题/知识点）
`knowledge_points` → `exercises`、`generated_exercises`（出题）
`users` → `push_tasks` → `push_logs`（推送）
`knowledge_docs`（知识库文档）

> 完整 DDL 在 `docs/03 §4`，字段名和 models.py 完全一致——这是约定：**文档是蓝本，代码照着做，不许另起炉灶改名。**

## 5. 读 `repositories/`：仓储模式

问题：模型类暴露给业务层，业务层就能到处写查询、绕过约束。
企业做法：**所有数据库访问收口到仓储层**，业务层只调仓库方法。

```
repositories/
├── base.py               ← 通用 CRUD：get_by_id / create / update / delete / list_page
├── user_repo.py          ← 只管 users 表
├── conversation_repo.py  ← 管 conversations + messages
├── knowledge_repo.py     ← 管 knowledge_docs + knowledge_points
├── homework_repo.py      ← 管 submissions + grading_results
├── mistake_repo.py
├── exercise_repo.py
└── push_repo.py          ← 管 push_tasks + push_logs
```

以 `user_repo.py` 为例：

```python
class UserRepository(BaseRepository):
    model = User                                    # ① 绑定表（模型类）
    def get_by_username(self, username: str) -> User | None:
        return self.session.query(User).filter(User.username == username).first()  # ② 具体查询
    def create_user(self, username, password_hash, ...):
        return self.create(username=username, password_hash=password_hash, ...)    # ③ 复用基类 create
```

- 基类 `BaseRepository.create` 用 `**fields` 建对象、`add` 到会话、`flush` 拿主键。
- 具体 repo 只写自己这张表的「专属方法」。
- **约定**：方法命名 `get_*` / `create_*` / `update_*` / `list_*`，返回 ORM 对象。

> 好处：以后把 MySQL 换成别的库，只要改 `repositories/` 和 `db.py`，业务层代码一行不动（docs/03 §1 的承诺）。

## 6. `init_db.py` 怎么把这些串起来

`Base.metadata.create_all(bind=engine)` → 建 12 张表 → `SessionLocal()` 开会话 → `KnowledgeRepository` / `UserRepository` 写内置数据 → `commit()` 落库。（`03` 里已经完整 trace 过一遍，回来复习。）

## 7. 动手练习

```bash
# ① 进 MySQL 看表结构和数据
mysql -uedumentor -pedumentor123 -D edumentor -e "SHOW TABLES;"
mysql -uedumentor -pedumentor123 -D edumentor -e "DESC messages;"
mysql -uedumentor -pedumentor123 -D edumentor -e "SELECT * FROM knowledge_points;"

# ② 用 Python 走一次仓储层（理解 ORM 与仓库的配合）
C:/Users/86176/.conda/envs/edumentor/python.exe -c "
from app.storage.db import SessionLocal
from app.storage.repositories import UserRepository
with SessionLocal() as s:
    u = UserRepository(s).get_by_username('demo')
    print('用户名:', u.username, '| 角色:', u.role, '| 密码哈希前20字符:', u.password_hash[:20])
"
```

## 8. 自检问题

- [ ] `engine` / `SessionLocal` / `Base` / `get_session` 各自是什么？
- [ ] 外键、JSON 列、默认值分别在 models.py 里怎么写？
- [ ] 为什么时间存 UTC？
- [ ] 仓储模式解决什么问题？`UserRepository` 和 `BaseRepository` 什么关系？
- [ ] 如果要把 MySQL 换成别的数据库，你要改哪些文件？
