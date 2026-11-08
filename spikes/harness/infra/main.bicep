// spike 用の使い捨て環境（harness 付きエージェントの確認）。本番の infra とは別の azd 環境で作り、確認後に azd down --purge で消す
targetScope = 'subscription'

@minLength(1)
@maxLength(64)
param environmentName string

@minLength(1)
param location string

@description('デプロイする人の object ID。エージェントの作成、接続の作成、確認用キューへの投入に使う')
param principalId string

@description('harness に使うモデル（推論とツール呼び出しに対応したもの）')
param modelName string
param modelVersion string

var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var tags = { 'azd-env-name': environmentName, purpose: 'spike' }

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

module identity 'modules/identity.bicep' = {
  scope: rg
  name: 'identity'
  params: { location: location, tags: tags, resourceToken: resourceToken }
}

module storage 'modules/storage.bicep' = {
  scope: rg
  name: 'storage'
  params: { location: location, tags: tags, resourceToken: resourceToken, deployerPrincipalId: principalId }
}

module mcpApp 'modules/mcp-app.bicep' = {
  scope: rg
  name: 'mcp-app'
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
    modelName: modelName
    modelVersion: modelVersion
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
    mcpTenantId: tenant().tenantId
    mcpAudiences: '${mcpApp.outputs.appId},${mcpApp.outputs.identifierUri}'
    foundryProjectEndpoint: foundry.outputs.projectEndpoint
  }
}

output AZURE_LOCATION string = location
output AZURE_TENANT_ID string = tenant().tenantId
output AZURE_RESOURCE_GROUP string = rg.name
output FOUNDRY_PROJECT_ENDPOINT string = foundry.outputs.projectEndpoint
output FOUNDRY_PROJECT_ID string = foundry.outputs.projectId
// azd ai connection create が、エンドポイントだけでは購読と RG を引けないため
output AZURE_AI_PROJECT_ID string = foundry.outputs.projectId
output MODEL_DEPLOYMENT string = foundry.outputs.modelDeployment
output EMBEDDING_DEPLOYMENT string = foundry.outputs.embeddingDeployment
output FUNCTION_APP_NAME string = functions.outputs.name
output MCP_URL string = '${functions.outputs.url}/api/mcp'
output MCP_AUDIENCE string = mcpApp.outputs.identifierUri
output MCP_APP_ID string = mcpApp.outputs.appId
output STORAGE_ACCOUNT_NAME string = storage.outputs.name
