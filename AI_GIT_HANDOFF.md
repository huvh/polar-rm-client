# AI / 维护者交接：Git 与仓库说明

> 给下一个 AI 或人类维护者：只读本文件即可接上当前 Git 状态。  
> **约束（用户明确要求）：不要修改主要项目业务文件**（`main.py`、`rm_client/**` 逻辑等），除非用户另说。

---

## 1. 仓库身份

| 项 | 值 |
|----|-----|
| 本地路径 | `C:\Users\lulu\Desktop\claude\openzenuicodexver\rm_custom_client` |
| GitHub | https://github.com/lulunomaro/polar-rm-client |
| 远程名 | `origin` |
| 默认分支 | `main` |
| 项目内容 | POLAR-RM 自定义客户端（Python + PySide6） |

**注意：** 父目录 `openzenuicodexver\` 是资料堆（开源参考、PDF、zip、视频）。  
**Git 仓库根只在 `rm_custom_client/`，不要对整个父目录做 `git init`。**

父目录可能存在**空的/无效** `openzenuicodexver\.git`（无 HEAD）。忽略它；有效仓库是本目录下的 `.git`。

---

## 2. 本次（2026-07-17）已完成的操作

1. 新增 `.gitignore`（忽略 `.venv`、缓存、tmp 截图、release zip、大视频壁纸、用户壁纸、校准数据等）。
2. 新增 `calibrations/.gitkeep`（保留空目录）。
3. 新增本文件 `AI_GIT_HANDOFF.md`。
4. 在 `rm_custom_client` 执行 `git init -b main`，首次提交桌面主线（286 文件）→ commit `fd06f52`。
5. 添加 remote `origin` → `https://github.com/lulunomaro/polar-rm-client.git`。
6. 远程原先仅有 GitHub 初始化的 `README.md`（`1864da2`）。已 `git pull --allow-unrelated-histories`；README 冲突时 **保留本地项目 README**（`git checkout --ours`），合并提交 `182f225`。
7. 已成功 `git push -u origin main`；本地与 `origin/main` 同步（HEAD = `182f225`）。
8. **未修改**任何业务源码逻辑（`main.py`、`rm_client/*.py` 等按原样入库，未做功能改动）。

### 故障排查（push 被拒 / 认证）

- `rejected (fetch first)`：远程有提交时先 `git pull origin main --allow-unrelated-histories`，解决冲突后再 push。
- 认证弹窗：Windows Credential Manager；或创建 GitHub PAT 后用 HTTPS 推送。
- 本机曾无 `gh` CLI / 无 SSH 私钥，当前成功路径是 HTTPS。

---

## 3. 刻意未纳入 Git 的内容

| 路径/类型 | 原因 |
|-----------|------|
| `.venv/` | ~1GB 虚拟环境，本机重建 |
| `tmp_render_checks/`、`tmp_*` | 调试截图 |
| `.wallpaper_cache/` | 运行缓存 |
| `release/*.zip` | 发布包体积大 |
| `assets/wallpapers/**/*.mp4` 等 | 大媒体；本机保留 |
| `assets/wallpapers/user/` | 用户导入 |
| `calibrations/*`（除 `.gitkeep`） | 机器相关 |
| `_backup_*` | 本地备份 |
| 父目录开源整仓 / PDF / zip | 不属于本仓库 |

克隆后需要：

```powershell
cd rm_custom_client   # 或 clone 下来的目录名
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
# 壁纸视频若需要，从原机 assets/wallpapers 拷回
```

---

## 4. 平行工作线（尚未导入本仓库）

用户另有一份**文件夹拷贝**当作 Gestalt 实验室分支：

- 路径：`G:\SteamLibrary\steamapps\common\GestaltSystem\RMaccseeplan\rm_custom_client`
- 含 `gestalt_*`、`input_bridge`、`start_lab_launcher.bat`、`workshop_telemetry_relay` 等
- 与桌面 `main` **已分叉**（互有独有文件），**尚未**作为 `gestalt-lab` 分支导入

**下一步（仅当用户要求时）：**

```powershell
cd C:\Users\lulu\Desktop\claude\openzenuicodexver\rm_custom_client
git checkout main
git checkout --orphan gestalt-lab
git rm -rf .   # 清空索引；确认 cwd 正确
robocopy "G:\SteamLibrary\steamapps\common\GestaltSystem\RMaccseeplan\rm_custom_client" . /E /XD .venv __pycache__ .git .wallpaper_cache tmp_render_checks tmp_selfcheck
# 保留本仓库的 .gitignore 与 AI_GIT_HANDOFF.md（若被覆盖则从 main 取回）
git checkout main -- .gitignore AI_GIT_HANDOFF.md
git add .
git commit -m "Import gestalt-lab snapshot from RMaccseeplan"
git push -u origin gestalt-lab
git checkout main
```

**不要**用整夹复制覆盖已跟踪的 Git 工作区来「同步」。

---

## 5. 本机 Git 账号状态（上次检查）

- 全局 `user.name` = `lulunomaro`
- 全局 `user.email` = `mhxiaoyao233@gmail.com`
- `credential.helper` = `manager`（Windows）
- **无** `gh` CLI；**无** SSH 私钥（仅 `known_hosts`）
- 推送依赖 HTTPS + Git Credential Manager / PAT

提交署名已配置；能否 push 取决于 GitHub 是否已在本机登录。

---

## 6. 日常命令（给人类 / AI）

```powershell
cd C:\Users\lulu\Desktop\claude\openzenuicodexver\rm_custom_client
git status
git add <paths>
git commit -m "简短说明"
git push
git pull
```

换分支前先 commit 或 `git stash`。

---

## 7. 开源与父目录资料

父目录参考项目（**不要**塞进本 repo）：OpenZen、Test-Client、ReGlass、AndroidLiquidGlass-kmp、LiquidBounce、DynamicIsland、gd656killicon、SharkDataSever 等。  
业务侧说明见 `THIRD_PARTY_NOTICES.md`。LiquidBounce 相关素材注意 GPL 合规；公开分发前再审。

---

## 8. 硬性约束（用户）

1. 不要改主要项目业务文件（除非用户明确要求功能开发）。
2. 不要把整个 `openzenuicodexver` 建成一个 monorepo。
3. 不要删除 G 盘 Gestalt 目录或桌面目录「为了干净」。
4. 有破坏性操作（force push、删分支、改历史）前先问用户。

---

## 9. 变更日志（追加）

| 日期 | 操作 | 操作者 |
|------|------|--------|
| 2026-07-17 | 初始化仓库、`.gitignore`、合并远程空 README、push `main`（`182f225`）、本交接文件 | Grok（本会话） |
