// 在原目录构造期间追加客户端条目。复用原图标/字体样式，原功能条目保持原身份和顺序。
const auto& additions=(*snapshots.front().frame)["_polarAdditionalNavigation"];
if(!additions.isNull())for(const auto& addition:array(additions,8)){
    const auto target=text(addition["target"]),title=text(addition["title"]);
    const auto alias=actionForTarget(text(addition["sourceAlias"]));
    need(alias.has_value()&&!actionForTarget(target),"Invalid client navigation alias");
    const auto action=static_cast<std::uint64_t>(entries_.size()+1);
    for(auto& surface:surfaces_){
        const Json* source=nullptr;
        for(const auto& candidate:surfaces_)if(candidate.kind==surface.kind){
            const auto found=candidate.variants.find(*alias);
            if(found!=candidate.variants.end()){source=&found->second;break;}
        }
        need(source,"Missing client navigation source style");
        auto content=localTree(*source,surface.id);
        if(surface.kind==NativeLabelKind::caption){
            const auto rename=[&](auto&& self,Json& node)->void{
                if(node["text"].isObject()){
                    node["text"]["string"]=title;node["text"]["runs"]=Json::Array{};
                }
                auto children=node["children"].array();
                for(auto& child:children)self(self,child);
                node["children"]=std::move(children);
            };
            rename(rename,content);
        }
        surface.variants.emplace(action,std::move(content));
    }
    entries_.push_back({action,target,title});navigation_.rightActions.push_back(action);
}
// 删除右侧重复入口及已移除的英雄部署；先保留原动作编号，再压紧导航布局。
for(const auto* target:{"nowPlaying","reader","mediaAssembly"}){
    const auto action=actionForTarget(target);
    need(action.has_value(),"Missing retired client navigation target");
    std::erase(navigation_.rightActions,*action);
    std::erase_if(entries_,[&](const auto& entry){return entry.action==*action;});
    for(auto& surface:surfaces_)surface.variants.erase(*action);
}
// 删项后条目会进入其他复用槽位；为新槽位复制同类的原版内容，保持图标及文字配对。
for(auto& surface:surfaces_)for(const auto& entry:entries_){
    if(surface.variants.contains(entry.action))continue;
    const Json* source=nullptr;
    for(const auto& candidate:surfaces_)if(candidate.kind==surface.kind){
        const auto found=candidate.variants.find(entry.action);
        if(found!=candidate.variants.end()){source=&found->second;break;}
    }
    need(source,"Missing retained navigation style");
    surface.variants.emplace(entry.action,localTree(*source,surface.id));
}
// 导出画面仍是旧排序；首帧必须刷新所有复用槽位的图标和标题。
initial_.clear();
