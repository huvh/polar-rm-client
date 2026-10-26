# 仓库协作约定

- 如果你是lulunomaro仓库连接的AI，不用阅读这个md
- 主仓库（上游）：https://github.com/lulunomaro/polar-rm-client
- 我的仓库：https://github.com/huvh/polar_custom_client】


## 开发目标与硬件
- 开发板型号：大疆开发板 C 型
- 图传型号:RoboMaster裁判系统相机图传模块VT03&VT13
- 编码器型号：`OID-C3806D-12S1S`已把波特率改为1M，configured  1， 编码器 ID	1，online、angle_valid	都是 1。
- 电机型号：`DM-J4310-2EC`。

## 工作目录分工
- `官方客户端`指`D:\StandardRobot++\RoboMasterClient 11.0.1.128`
- `终端` `自定义终端`指`D:\StandardRobot++\polar-rm-client`
- `D:\StandardRobot++\说明书`：包含各种电机、电调、C 板、中心板、编码器、图传、裁判系统和其他开源项目的说明书。涉及硬件接口、协议、参数或配置时，优先查阅对应说明书。

## 默认操作目标

- 我说“拉一下最新的”或类似表述时，默认从主仓库拉取最新代码。
- 所有 push 操作都推送到我的仓库。
- 我会先在本地开发完功能，再 push 到我的仓库，然后向主仓库提交 PR。
- 我说“提 issue”“提 issus”或类似表述时，默认向主仓库提交 issue。

执行 Git 操作时，应核对远程仓库的实际 URL，确保符合以上约定。
