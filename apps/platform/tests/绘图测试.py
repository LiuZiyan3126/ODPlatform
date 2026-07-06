import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import matplotx

# 读取数据
df = pd.read_csv(r'C:\Users\Lenovo\Desktop\ODPlatform\apps\platform\tests\results.csv')
# print(plt.style.available)
plt.style.use(matplotx.styles.pitaya_smoothie['light'])
plt.rcParams['font.family'] = ['Times New Roman', 'STsong'] # 设置字体

# 创建画布，设置合适的布局
fig, axes = plt.subplots(3, 2, figsize=(16, 18))
fig.suptitle('目标检测模型训练过程可视化', fontsize=16, y=0.995)

# 1. 损失曲线（训练 vs 验证）
ax1 = axes[0, 0]
ax1.plot(df['epoch'], df['train/box_loss'], label='Train Box Loss')
ax1.plot(df['epoch'], df['val/box_loss'], label='Val Box Loss')
ax1.plot(df['epoch'], df['train/cls_loss'], label='Train CLS Loss')
ax1.plot(df['epoch'], df['val/cls_loss'], label='Val CLS Loss')
ax1.plot(df['epoch'], df['train/dfl_loss'], label='Train DFL Loss')
ax1.plot(df['epoch'], df['val/dfl_loss'], label='Val DFL Loss')
ax1.set_xlabel('Epoch')
ax1.set_ylabel('Loss')
ax1.set_title('训练和验证损失曲线')
ax1.legend()
ax1.grid(True)

# 2. 评估指标曲线
ax2 = axes[0, 1]
ax2.plot(df['epoch'], df['metrics/precision(B)'], label='Precision')
ax2.plot(df['epoch'], df['metrics/recall(B)'], label='Recall')
ax2.plot(df['epoch'], df['metrics/mAP50(B)'], label='mAP@50')
ax2.plot(df['epoch'], df['metrics/mAP50-95(B)'], label='mAP@50-95')
ax2.set_xlabel('Epoch')
ax2.set_ylabel('Score')
ax2.set_title('评估指标变化趋势')
ax2.legend()
ax2.grid(True)

# 3. 学习率变化曲线
ax3 = axes[1, 0]
ax3.plot(df['epoch'], df['lr/pg0'], label='lr/pg0')
ax3.plot(df['epoch'], df['lr/pg1'], label='lr/pg1')
ax3.plot(df['epoch'], df['lr/pg2'], label='lr/pg2')
ax3.set_xlabel('Epoch')
ax3.set_ylabel('Learning Rate')
ax3.set_title('学习率调度曲线')
ax3.legend()
ax3.grid(True)

# 4. 总损失对比
ax4 = axes[1, 1]
train_total_loss = df['train/box_loss'] + df['train/cls_loss'] + df['train/dfl_loss']
val_total_loss = df['val/box_loss'] + df['val/cls_loss'] + df['val/dfl_loss']
ax4.plot(df['epoch'], train_total_loss, label='Train Total Loss')
ax4.plot(df['epoch'], val_total_loss, label='Val Total Loss')
ax4.set_xlabel('Epoch')
ax4.set_ylabel('Total Loss')
ax4.set_title('总损失对比')
ax4.legend()
ax4.grid(True)

# 5. 训练时间
ax5 = axes[2, 0]
ax5.plot(df['epoch'], df['time'], marker='.', markersize=2)
ax5.set_xlabel('Epoch')
ax5.set_ylabel('Time (s)')
ax5.set_title('每个epoch训练时间')
ax5.grid(True)

# 6. mAP综合指标
ax6 = axes[2, 1]
ax6.plot(df['epoch'], df['metrics/mAP50(B)'], label='mAP@50')
ax6.plot(df['epoch'], df['metrics/mAP50-95(B)'], label='mAP@50-95')
# 添加平均值线
ax6.axhline(df['metrics/mAP50(B)'].mean(), linestyle='--', alpha=0.7, 
           label=f'mAP@50 Avg: {df["metrics/mAP50(B)"].mean():.4f}')
ax6.axhline(df['metrics/mAP50-95(B)'].mean(), linestyle='--', alpha=0.7, 
           label=f'mAP@50-95 Avg: {df["metrics/mAP50-95(B)"].mean():.4f}')
ax6.set_xlabel('Epoch')
ax6.set_ylabel('mAP Score')
ax6.set_title('mAP指标变化（含平均值）')
ax6.legend()
ax6.grid(True)

# 调整布局，防止标签重叠
plt.tight_layout()

# 显示图表
plt.show()

# 可选：保存图片
plt.savefig('training_results.png', dpi=300, bbox_inches='tight')