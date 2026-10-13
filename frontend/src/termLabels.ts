const types: Record<string, string> = { concept: "概念", entity: "命名实体", vocabulary: "专业词汇" };
const depths: Record<string, string> = { stub: "基础速览", standard: "标准理解", deep: "系统深入" };
export const termTypeLabel = (value: string) => types[value] ?? value;
export const termDepthLabel = (value: string) => depths[value] ?? value;
