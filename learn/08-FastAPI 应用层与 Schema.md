# 08 · FastAPI 应用层与 Schema（API 契约）

> 目标：看懂 `app/main.py` 怎么把整个应用组装起来，以及 `app/schemas/` 为什么是"先定契约、再写实现"的关键。
> 对照文件：`app/main.py`、`app/api/health.py`、`app/schemas/`、`app/core/exceptions.py`。

---

## 1. 一个 FastAPI 应用 = 四件事

打开 `app/main.py`，它只做了四件事：

```
① 创建应用      app = FastAPI(title=..., version=..., lifespan=lifespan)
② 注册异常处理  @app.exception_handler(...)  把异常统一转 JSON
③ 挂载路由      app.include_router(health_router, prefix="/api/v1")
④ 托管前端      @app.get("/") + app.mount("/static", ...)
```

### ① 创建应用
`FastAPI()` 接收应用名、版本号；`lifespan` 是「启动/关闭钩子」——服务启动时执行（这里初始化日志）。

### ② 异常处理（企业级必考）
目标：**不管哪里出错，接口返回的 JSON 都是统一结构**：

```json
{ "code": "LLM_ERROR", "message": "上游模型调用失败", "detail": "Timeout after 30s" }
```

做法：自定义异常类（`app/core/exceptions.py`）都继承 `EduMentorError`，它有 `code` / `status_code` / `message` / `detail`；`main.py` 注册处理器把异常转成上面这个 JSON。

```python
class EduMentorError(Exception):
    code = "INTERNAL_ERROR"
    status_code = 500
    def to_dict(self):
        return {"code": self.code, "message": self.message, "detail": self.detail}

class ResourceNotFoundError(EduMentorError):   # 派生：404
    code = "NOT_FOUND"
    status_code = 404
```

- 业务代码抛 `ResourceNotFoundError("xx 不存在")`，前端就收到结构统一的 404 响应。
- **好处**：前端只需要处理一种错误格式；日志里能精准定位错误类型。

### ③ 挂载路由
`app/api/` 里每个文件定义一个 `router`，再统一挂到 `app`：

```python
# app/api/health.py
router = APIRouter()

@router.get("/health", tags=["system"])
def health_check() -> dict:
    ...
```

```python
# app/main.py
app.include_router(health_router, prefix="/api/v1")   # → 实际路径 /api/v1/health
```

以后每加一个 Agent 的接口（auth/chat/homework...），就是**新建一个 api 文件 + 在 main.py 里 include_router 一行**。

## 2. 路由函数为什么是普通 `def` 而不是 `async def`？

`health_check` 里调了 `engine.connect()`（数据库，是**阻塞操作**）。

FastAPI 的规则：**`def` 路由会被自动丢进线程池执行，不阻塞主事件循环**。所以"阻塞操作用 `def`，轻量异步才用 `async def`"是项目的硬规范（docs/08 §8）。

> 等阶段二做 SSE 流式时，`async def` + 生成器就会出现，现在先记住这个区别。

## 3. Schema（Pydantic 模型）：API 的"合同"

### 为什么要先写 Schema？

`app/schemas/` 里的类定义了「接口收什么、返回什么」：

```python
# app/schemas/auth.py
class LoginRequest(BaseModel):        # 请求体：登录要收这两个字段
    username: str
    password: str

class TokenOut(BaseModel):            # 响应体：登录要返回这两块
    token: str
    user: UserOut
```

作用（4 个）：

| 作用 | 说明 |
|------|------|
| 请求校验 | 传错字段/类型，FastAPI 直接返回 400，不用自己写 if |
| 响应定型 | 返回的数据只保留 Schema 声明的字段，不会多漏 |
| 生成文档 | Swagger（/docs）自动展示请求/响应结构 |
| 类型安全 | 写代码时 IDE 有提示，别传错 |

### 一个小语法：`model_config = ConfigDict(from_attributes=True)`

表示「可以直接从 ORM 对象转成这个 Schema」。比如 `UserOut` 定义了这个，就能 `UserOut.model_validate(user_obj)` 把数据库里的 User 对象直接变成响应。

## 4. 一次完整走通：health 接口（复习 + 串讲）

```
GET /api/v1/health
  → 匹配 app/api/health.py 的 health_check()
  → services/health_service.py 的 check_database()：engine 连 MySQL 执行 SELECT 1
  → 返回 dict：{"status","app","version","db","llm"}
  → FastAPI 自动序列化成 JSON
```

阶段一只有这一个接口。等阶段二 `app/api/chat.py` 出现，你会看到 `async def` + SSE + 依赖注入（`Depends(get_session)`），模式是一样的。

## 5. 动手练习

给自己加一个最简单的接口，亲自看 docs 变化：

```python
# app/api/health.py 里加（临时实验，学会后可删）
@router.get("/ping")
def ping() -> dict:
    return {"pong": "hello from EduMentor"}
```

重启 uvicorn 后：

```bash
curl http://localhost:8000/api/v1/ping      # {"pong":"hello from EduMentor"}
curl http://localhost:8000/docs             # 左侧能看到新增的 GET /api/v1/ping
```

## 6. 自检问题

- [ ] `main.py` 做了哪四件事？用一句话概括每个。
- [ ] 为什么所有异常类都继承 `EduMentorError`？（统一错误格式）
- [ ] `include_router(..., prefix="/api/v1")` 是什么意思？
- [ ] Schema 的四个作用是什么？`from_attributes=True` 是干什么的？
- [ ] 阻塞的数据库操作，路由应该用 `def` 还是 `async def`？为什么？
