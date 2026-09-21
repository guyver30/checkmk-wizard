import { newSpecPage } from '@stencil/core/testing';
import { KfdsCheckbox } from '../kfds-checkbox';

describe('kfds-checkbox', () => {
  it('renders', async () => {
    const page = await newSpecPage({
      components: [ KfdsCheckbox],
      html: `<kfds-checkbox></kfds-checkbox>`,
    });
    expect(page.root).toEqualHtml(`
      <kfds-checkbox>
        <mock:shadow-root>
          <slot></slot>
        </mock:shadow-root>
      </kfds-checkbox>
    `);
  });
});
