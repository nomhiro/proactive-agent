// Azure Functions（Flex Consumption、Python 3.12）。接続はすべてユーザー割り当てマネージド ID で行う
param location string
param tags object
param resourceToken string
param identityId string
param identityClientId string
param identityPrincipalId string
param storageAccountName string
param deploymentContainerUrl string
param appInsightsName string
param appInsightsConnectionString string
param cosmosEndpoint string
param cosmosDatabase string
param webPubSubEndpoint string
param webPubSubHub string
param gatewayTenantId string
@description('書き込み窓口が受け付けるトークンの aud（カンマ区切り）')
param gatewayAudiences string
@description('HILS ログを読む Blob のエンドポイント')
param blobEndpoint string
@description('エージェントの起動、Routines の手動起動、Memory ストアに使う Foundry のプロジェクト')
param foundryProjectEndpoint string
param memoryStoreName string

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: appInsightsName
}

var storageRoles = [
  'b7e6dc6d-f1e8-4753-8033-0f276bb0955b' // Storage Blob Data Owner
  '974c5e8b-45b9-4653-ba55-5f855dd0fb88' // Storage Queue Data Contributor
  '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3' // Storage Table Data Contributor
]

resource storageRoleAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for roleId in storageRoles: {
    scope: storage
    name: guid(storage.id, identityPrincipalId, roleId)
    properties: {
      principalId: identityPrincipalId
      principalType: 'ServicePrincipal'
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleId)
    }
  }
]

// 3913510d-42f4-4e42-8a64-420c390055eb = Monitoring Metrics Publisher
resource metricsPublisher 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: appInsights
  name: guid(appInsights.id, identityPrincipalId, 'metrics-publisher')
  properties: {
    principalId: identityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '3913510d-42f4-4e42-8a64-420c390055eb')
  }
}

resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: 'plan-${resourceToken}'
  location: location
  tags: tags
  kind: 'functionapp'
  sku: { tier: 'FlexConsumption', name: 'FC1' }
  properties: { reserved: true }
}

resource app 'Microsoft.Web/sites@2024-04-01' = {
  name: 'func-${resourceToken}'
  location: location
  tags: union(tags, { 'azd-service-name': 'functions' })
  kind: 'functionapp,linux'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identityId}': {} }
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: deploymentContainerUrl
          authentication: {
            type: 'UserAssignedIdentity'
            userAssignedIdentityResourceId: identityId
          }
        }
      }
      scaleAndConcurrency: { maximumInstanceCount: 40, instanceMemoryMB: 2048 }
      runtime: { name: 'python', version: '3.12' }
    }
    siteConfig: {
      minTlsVersion: '1.2'
      appSettings: [
        { name: 'AzureWebJobsStorage__credential', value: 'managedidentity' }
        { name: 'AzureWebJobsStorage__clientId', value: identityClientId }
        { name: 'AzureWebJobsStorage__blobServiceUri', value: storage.properties.primaryEndpoints.blob }
        { name: 'AzureWebJobsStorage__queueServiceUri', value: storage.properties.primaryEndpoints.queue }
        { name: 'AzureWebJobsStorage__tableServiceUri', value: storage.properties.primaryEndpoints.table }
        { name: 'COSMOS__accountEndpoint', value: cosmosEndpoint }
        { name: 'COSMOS__credential', value: 'managedidentity' }
        { name: 'COSMOS__clientId', value: identityClientId }
        { name: 'COSMOS_ENDPOINT', value: cosmosEndpoint }
        { name: 'COSMOS_DATABASE', value: cosmosDatabase }
        { name: 'WEBPUBSUB_ENDPOINT', value: webPubSubEndpoint }
        { name: 'WEBPUBSUB_HUB', value: webPubSubHub }
        { name: 'GATEWAY_TENANT_ID', value: gatewayTenantId }
        { name: 'GATEWAY_AUDIENCES', value: gatewayAudiences }
        { name: 'AGENT_INVOKER', value: 'foundry' }
        { name: 'FOUNDRY_PROJECT_ENDPOINT', value: foundryProjectEndpoint }
        { name: 'MEMORY_STORE_NAME', value: memoryStoreName }
        { name: 'AZURE_STORAGE_BLOB_ENDPOINT', value: blobEndpoint }
        { name: 'AZURE_CLIENT_ID', value: identityClientId }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
        { name: 'APPLICATIONINSIGHTS_AUTHENTICATION_STRING', value: 'ClientId=${identityClientId};Authorization=AAD' }
      ]
    }
  }
  dependsOn: [storageRoleAssignments, metricsPublisher]
}

output name string = app.name
output url string = 'https://${app.properties.defaultHostName}'
