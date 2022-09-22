import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
sns.set_style("darkgrid", {"axes.facecolor": ".9"})

PAPER_VERSION = True
from matplotlib import rc
rc('font', **{'family':'serif', 'serif':['Times']})

# groups = ['Text', 'Value', 'Image', 'Geometry']

groups = ['Object', 'Value', 'Text', 'Init', 'Geometry']
group_names = ['(a) Object embedding', '(b) Value embedding', '(c) Text embedding',
               '(d) Init sequence', '(e) Geometry']

# models = [
#     'baseline', 'rel=no_init', 'rel=one-hot',
#     'val=no-value', 'val=no-pose', 'val=no-position',
#     'baseline', 'img=feature', 'img=one-hot',
#     'img=one-hot', 'val=no-value', 'img=one-hot\nval=no-value',
# ]
models = [
    'baseline', 'img=feature', 'img=one-hot',
    'val=no-value', 'val=no-pose', 'val=no-position',
    'baseline', 'rel=one-hot',
    'baseline', 'rel=all', 'rel=no_init',
    'baseline', 'img=one-hot', 'val=no-value', 'img=one-hot\nval=no-value',
]

areas = ['Object', 'Object', 'Object',
         'Value', 'Value', 'Value',
         'Text', 'Text',
         'Init', 'Init',
         'Geometry', 'Geometry', 'Geometry', 'Geometry']
areas = [group_names[groups.index(area)] for area in areas]

df = pd.DataFrame({
    # 'Area': ['Relation', 'Relation', 'Relation',
    #          'Value', 'Value', 'Value',
    #          'Image', 'Image', 'Image',
    #          'Geometry', 'Geometry', 'Geometry'],
    # 'Rank': ['PST', '−init', '−text',
    #          '−value', '−pose', '−position',
    #          '−one-hot', '−img', 'PST',
    #          '−img', '−value', '−img −value'],
    'Area': areas,
    'Rank': ['CLIP feature', 'one-hot', 'both',
             'no value', 'no pose', 'no position',
             'CLIP feature', 'one-hot',
             'random-drop', 'none',
             'PST', 'no img', 'no value', 'no both'],
    # 'Training Accuracy': [
    #     0.955, ## baseline
    #     0.723, ## rel=no_init
    #     0.878, ## rel=one-hot - 178
    #     # 0.95, ## rel=all
    #     0.913, ## val=no-value
    #     0.934, ## val=no-pose
    #     0.944 ## val=no-position
    #     0.943, ## img=feature
    #     0.866, ## img=one-hot
    #     0.746, ## img=one-hot|relno-value - 150
    # ],
    'Accuracy': [
        0.921, ## img=feature
        0.881, ## img=one-hot
        0.916, ## baseline

        0.9,  ## val=no-value
        0.89,  ## val=no-pose
        0.911,  ## val=no-position

        0.916,  ## baseline
        0.846, ## rel=one-hot

        0.916,  ## baseline
        # 0.918, ## rel=all
        0.741, ## rel=no_init

        0.916,  ## baseline
        0.881, ## img=one-hot
        0.9, ## val=no-value
        0.774, ## img=one-hot|relno-value - 150
    ],
    'True Positive Rate': [
        0.9261, ## img=feature
        0.8522, ## img=one-hot
        0.931, ## baseline

        0.8867,  ## val=no-value
        0.9113,  ## val=no-pose
        0.9409,  ## val=no-position

        0.931, ## baseline
        0.7685, ## rel=one-hot - 178

        0.931,  ## baseline
        # 0.9113, ## rel=all
        0.8276, ## rel=no_init

        0.931,  ## baseline
        0.8522, ## img=one-hot
        0.8867, ## val=no-value
        0.7685, ## img=one-hot|relno-value - 150
    ],
    ' True Negative Rate': [
        0.9159, ## img=feature
        0.9071, ## img=one-hot
        0.9027, ## baseline

        0.9115,  ## val=no-value
        0.8717,  ## val=no-pose
        0.885,  ## val=no-position

        0.9027,  ## baseline
        0.9159, ## rel=one-hot - 178

        0.9027,  ## baseline
        # 0.9248, ## rel=all
        0.6637, ## rel=no_init

        0.9027,  ## baseline
        0.9071, ## img=one-hot
        0.9115, ## val=no-value
        0.7788, ## img=one-hot|relno-value - 150
    ],
})
df = df.set_index(['Area', 'Rank'])

figsize = (12, 4) if not PAPER_VERSION else (15, 3)
fig = plt.figure(figsize=figsize)
if not PAPER_VERSION:
    plt.title('Ablation studies on classification accuracy', fontsize=16, pad=35)
else:
    plt.title(' ', fontsize=16, pad=5)
plt.axis('off')

colors = ['b', 'g', 'r'] ## 'y',
colors = ['#3498db', '#2ecc71', '#e74c3c'] ## '#f1c40f',

for i, l in enumerate(group_names):
    if i == 0:
        sub1 = fig.add_subplot(151+i)
    else:
        sub1 = fig.add_subplot(151+i, sharey=sub1)

    df.loc[l].plot(kind='bar', ax=sub1, color=colors)
    sub1.set_xticklabels(sub1.get_xticklabels(), rotation=0, fontsize=10)
    sub1.set_xlabel(l, fontsize=12)
    sub1.tick_params(axis='x', which='major', pad=0)
    sub1.get_legend().remove()
    sub1.set_ylim([0.65, 1.0])

    ## remove the edge color auto generated by dataframe.plot
    for i in range(len(sub1.__dict__['containers'])):
        for j in range(len(sub1.__dict__['containers'][i].__dict__['patches'])):
            sub1.__dict__['containers'][i].__dict__['patches'][j].__dict__['_edgecolor'] = (1, 1, 1, 0)

    # import ipdb; ipdb.set_trace()

handles, labels = sub1.get_legend_handles_labels()
if not PAPER_VERSION:
    fig.legend(handles, labels, ncol=5, loc='upper center', bbox_to_anchor=(0.5, 0.9))
else:
    fig.legend(handles, labels, ncol=5, loc='upper center', bbox_to_anchor=(0.5, 0.98))
plt.tight_layout()

if PAPER_VERSION:
    plt.savefig('/home/yang/ablations.pdf', bbox_inches='tight')
else:
    plt.show()