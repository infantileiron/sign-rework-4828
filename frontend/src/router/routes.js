export const modules = [
  ['orders', '工单样本', '▤'], ['plans', '候选特征', '▥'], ['runs', '按组交叉验证', '⌗'], ['reports', '排期解释', '▱'], ['schedule', '排班调度', '▦'],
];
export function activeRoute() {
  const [, page = '', id = ''] = location.hash.split('/');
  return [modules.some(([key]) => key === page) ? page : 'orders', /^\d+$/.test(id) ? id : ''];
}
