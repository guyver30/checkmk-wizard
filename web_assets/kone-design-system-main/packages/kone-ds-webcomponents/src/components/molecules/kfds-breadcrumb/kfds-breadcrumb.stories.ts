import { BreadcrumbSize, BreadcrumbType } from './kfds-breadcrumb.enum';

export default {
  // this creates a ‘Components’ folder and a Breadcrumb subfolder
  title: 'Components/Breadcrumb',
  tags: ['autodocs'],
  argTypes: {
      type: { 
          control: { type: "select" },
          options: [BreadcrumbType.Default, BreadcrumbType.Background]
      },
      size: { 
          control: { type: "select" },
          options: [BreadcrumbSize.Small, BreadcrumbSize.Medium]
      },
      itemClicked: { action: 'itemClicked', table: { type: { summary: 'EventEmitter' } } },
  },
  render: ({ ...args }) => {
      return `<kfds-breadcrumb is-truncated=${args.isTruncated} links='${JSON.stringify(args.links)}' type='${args.type}' size='${args.size}'></kfds-breadcrumb>`;
  },
  parameters: {
        docs: {
            source: { 
              code: `// React
import { KfdsBreadcrumb } from '@kone-ds/webcomponents-react';
import { BreadcrumbSize, BreadcrumbType } from '@kone-ds/webcomponents';

const breadcrumbLinks = [{
  label: 'Link 1',
  path: 'path1'
},
{
  label: 'Link 2',
  path: 'path2'
}];

<KfdsBreadcrumb
  size={BreadcrumbSize.Medium}
  type={BreadcrumbType.Default}
  links={breadcrumbLinks}
  onItemClicked={(event) => console.log('Breadcrumb clicked', event)}
/>`,
            },
          },
      }
};

const links = [{
  label: 'Home',
  path: '/home',
},
{
  label: 'Link 1',
  path: '/link1',
},
{
  label: 'Link 2',
  path: '/link2',
},
{
  label: 'Link 3'
}];


export const Breadcrumb = { 
  args: {
      type: BreadcrumbType.Default,
      size: BreadcrumbSize.Medium,
      links: links,
      isTruncated: false
  }
};
