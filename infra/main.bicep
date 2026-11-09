// proactive-agent の基盤一式（Plan 2、Plan 3 で Foundry、Plan 4 で Web アプリを追加）。azd up で作る。
targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('azd の環境名')
param environmentName string

@minLength(1)
@description('地域。japaneast を想定（README の「地域」）')
param location string

@description('デプロイする人の object ID。シード投入のために Cosmos のデータ権限を付ける')
param principalId string = ''

@description('エージェントが使うモデル（Foundry のデプロイ名も同じ）')
param modelName string = 'gpt-5.4-mini'
param modelVersion string = '2026-03-17'
@description('モデルのレートの上限（1000 トークン/分）。GlobalStandard は使った分だけの課金で、容量に固定費はかからない')
param modelCapacity int = 500

@description('チームの記憶を置く Foundry Memory の Memory ストアの名前。ストアはフックが作る')
param memoryStoreName string = 'team-memory'

var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var tags = { 'azd-env-name': environmentName }

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module monitoring 'modules/monitoring.bicep' = {
  scope: rg
  name: 'monitoring'
  params: { location: location, tags: tags, resourceToken: resourceToken }
}

module storage 'modules/storage.bicep' = {
  scope: rg
  name: 'storage'
  params: { location: location, tags: tags, resourceToken: resourceToken, deployerPrincipalId: principalId }
}

module identity 'modules/identity.bicep' = {
  scope: rg
  name: 'identity'
  params: { location: location, tags: tags, resourceToken: resourceToken }
}

// Web アプリ（BFF）の ID（Plan 4）
module webIdentity 'modules/identity.bicep' = {
  scope: rg
  name: 'identity-web'
  params: { location: location, tags: tags, resourceToken: resourceToken, prefix: 'web' }
}

module cosmos 'modules/cosmos.bicep' = {
  scope: rg
  name: 'cosmos'
  params: {
    location: location
    tags: tags
    resourceToken: resourceToken
    dataContributorPrincipalIds: empty(principalId)
      ? [identity.outputs.principalId, webIdentity.outputs.principalId]
      : [identity.outputs.principalId, webIdentity.outputs.principalId, principalId]
  }
}

module webPubSub 'modules/webpubsub.bicep' = {
  scope: rg
  name: 'webpubsub'
  params: {
    location: location
    tags: tags
    resourceToken: resourceToken
    ownerPrincipalIds: [identity.outputs.principalId, webIdentity.outputs.principalId]
  }
}

module gatewayApp 'modules/gateway-app.bicep' = {
  scope: rg
  name: 'gateway-app'
  params: { environmentName: environmentName, resourceToken: resourceToken }
}

module foundry 'modules/foundry.bicep' = {
  scope: rg
  name: 'foundry'
  params: {
    location: location
    tags: tags
    resourceToken: resourceToken
    deployerPrincipalId: principalId
    functionPrincipalId: identity.outputs.principalId
    webPrincipalId: webIdentity.outputs.principalId
    modelName: modelName
    modelVersion: modelVersion
    modelCapacity: modelCapacity
  }
}

module functions 'modules/functions.bicep' = {
  scope: rg
  name: 'functions'
  params: {
    location: location
    tags: tags
    resourceToken: resourceToken
    identityId: identity.outputs.id
    identityClientId: identity.outputs.clientId
    identityPrincipalId: identity.outputs.principalId
    storageAccountName: storage.outputs.name
    deploymentContainerUrl: storage.outputs.deploymentContainerUrl
    appInsightsName: monitoring.outputs.appInsightsName
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    cosmosEndpoint: cosmos.outputs.endpoint
    cosmosDatabase: cosmos.outputs.databaseName
    webPubSubEndpoint: webPubSub.outputs.endpoint
    webPubSubHub: webPubSub.outputs.hub
    gatewayTenantId: tenant().tenantId
    gatewayAudiences: '${gatewayApp.outputs.appId},${gatewayApp.outputs.identifierUri}'
    blobEndpoint: storage.outputs.blobEndpoint
    foundryProjectEndpoint: foundry.outputs.projectEndpoint
    memoryStoreName: memoryStoreName
  }
}

module web 'modules/web.bicep' = {
  scope: rg
  name: 'web'
  params: {
    location: location
    tags: tags
    resourceToken: resourceToken
    environmentName: environmentName
    identityId: webIdentity.outputs.id
    identityClientId: webIdentity.outputs.clientId
    identityPrincipalId: webIdentity.outputs.principalId
    logAnalyticsId: monitoring.outputs.logAnalyticsId
    cosmosEndpoint: cosmos.outputs.endpoint
    cosmosDatabase: cosmos.outputs.databaseName
    foundryProjectEndpoint: foundry.outputs.projectEndpoint
    memoryStoreName: memoryStoreName
    webPubSubEndpoint: webPubSub.outputs.endpoint
    webPubSubHub: webPubSub.outputs.hub
    principalId: principalId
  }
}

output AZURE_LOCATION string = location
output AZURE_TENANT_ID string = tenant().tenantId
output AZURE_RESOURCE_GROUP string = rg.name
output COSMOS_ENDPOINT string = cosmos.outputs.endpoint
output COSMOS_DATABASE string = cosmos.outputs.databaseName
output FUNCTION_APP_NAME string = functions.outputs.name
output FUNCTION_APP_URL string = functions.outputs.url
output WEBPUBSUB_ENDPOINT string = webPubSub.outputs.endpoint
output WEBPUBSUB_HUB string = webPubSub.outputs.hub
output GATEWAY_APP_ID string = gatewayApp.outputs.appId
output GATEWAY_APP_ID_URI string = gatewayApp.outputs.identifierUri
output AZURE_STORAGE_BLOB_ENDPOINT string = storage.outputs.blobEndpoint
output FOUNDRY_ACCOUNT_NAME string = foundry.outputs.accountName
output FOUNDRY_ACCOUNT_ID string = foundry.outputs.accountId
output FOUNDRY_PROJECT_ENDPOINT string = foundry.outputs.projectEndpoint
output FOUNDRY_PROJECT_ID string = foundry.outputs.projectId
output AZURE_AI_PROJECT_ID string = foundry.outputs.projectId
output MODEL_DEPLOYMENT string = foundry.outputs.modelDeployment
output EMBEDDING_DEPLOYMENT string = foundry.outputs.embeddingDeployment
output MEMORY_STORE_NAME string = memoryStoreName
output APPLICATIONINSIGHTS_CONNECTION_STRING string = monitoring.outputs.appInsightsConnectionString
output WEB_URL string = web.outputs.url
output WEB_APP_NAME string = web.outputs.name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = web.outputs.registryEndpoint
