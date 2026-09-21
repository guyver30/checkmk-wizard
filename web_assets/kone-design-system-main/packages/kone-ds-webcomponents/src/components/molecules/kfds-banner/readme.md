# kfds-banner



<!-- Auto Generated Below -->


## Properties

| Property      | Attribute      | Description | Type                                                                              | Default              |
| ------------- | -------------- | ----------- | --------------------------------------------------------------------------------- | -------------------- |
| `actions`     | `actions`      |             | `any`                                                                             | `undefined`          |
| `customClass` | `custom-class` |             | `string`                                                                          | `''`                 |
| `elementId`   | `element-id`   |             | `string`                                                                          | `undefined`          |
| `message`     | `message`      |             | `string`                                                                          | `undefined`          |
| `position`    | `position`     |             | `BannerPosition.Bottom \| BannerPosition.Top`                                     | `BannerPosition.Top` |
| `type`        | `type`         |             | `BannerType.Error \| BannerType.Info \| BannerType.Success \| BannerType.Warning` | `BannerType.Info`    |


## Events

| Event               | Description | Type                  |
| ------------------- | ----------- | --------------------- |
| `actionLinkClicked` |             | `CustomEvent<string>` |


## Shadow Parts

| Part                 | Description |
| -------------------- | ----------- |
| `"banner-container"` |             |
| `"close"`            |             |
| `"hyperlink"`        |             |
| `"icon"`             |             |
| `"message"`          |             |


## Dependencies

### Depends on

- [kfds-hyperlink](../../atoms/kfds-hyperlink)

### Graph
```mermaid
graph TD;
  kfds-banner --> kfds-hyperlink
  style kfds-banner fill:#f9f,stroke:#333,stroke-width:4px
```

----------------------------------------------

*Built with [StencilJS](https://stenciljs.com/)*
