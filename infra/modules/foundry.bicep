// Foundry のアカウント、プロジェクト、モデルのデプロイ、ロール（Plan 3）。キーは無効にし、Entra だけで使う。
// エージェント、MCP 接続、Routines、RAI ポリシー、エージェント ID へのロールは、エージェントができてから
// azd のフック（deploy/proactive_deploy）が作る（設計書 7.10 節）
param location string
param tags object
param resourceToken string
@description('デプロイする人の object ID。空ならデプロイする人へのロールは付けない')
param deployerPrincipalId string = ''
param functionPrincipalId string
param modelName string
param modelVersion string
@description('モデルのレートの上限（1000 トークン/分）。4体が同時に動くと 50 では足りず rate_limit_exceeded になった')
param modelCapacity int = 500
param embeddingCapacity int = 50
@description('Foundry Memory の索引に使う埋め込みモデル（Plan 3 決定 13）')
param embeddingName string = 'text-embedding-3-small'
param embeddingVersion string = '1'

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: 'aif-${resourceToken}'
  location: location
  tags: tags
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: 'aif-${resourceToken}'
    allowProjectManagement: true
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource deployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: account
  name: modelName
  sku: { name: 'GlobalStandard', capacity: modelCapacity }
  properties: {
    model: { format: 'OpenAI', name: modelName, version: modelVersion }
  }
}

resource embedding 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: account
  name: embeddingName
  sku: { name: 'GlobalStandard', capacity: embeddingCapacity }
  properties: {
    model: { format: 'OpenAI', name: embeddingName, version: embeddingVersion }
  }
  dependsOn: [deployment] // 同じアカウントへのデプロイは1つずつ
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: account
  name: 'proj-proactive'
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: 'proactive vehicle agents'
    description: '架空SUV のチームアシスタント3体と車種統括エージェント'
  }
  dependsOn: [embedding]
}

// ロールは名前の変更中のため GUID で指定する（ドキュメントの注記どおり）
var foundryUser = '53ca6127-db72-4b80-b1b0-d745d6d5456d'
var foundryProjectManager = 'eadc314b-1a2d-4efa-be10-5d325db5065e'
// Memory ストアの埋め込みモデルの呼び出しに要る。アカウントのスコープでないと 401 になった（設計書 7.7 節）
var openAiUser = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

var deployer = empty(deployerPrincipalId) ? [] : [
  { principalId: deployerPrincipalId, principalType: 'User', roleId: foundryUser }
  { principalId: deployerPrincipalId, principalType: 'User', roleId: foundryProjectManager }
]

// プロジェクトのスコープ: エージェントの起動、Routines の手動起動、Memory ストアの API
var projectAssignments = concat(deployer, [
  { principalId: functionPrincipalId, principalType: 'ServicePrincipal', roleId: foundryUser }
])

// アカウントのスコープ: Memory ストアが埋め込みモデルを呼ぶための権限
var deployerOpenAi = empty(deployerPrincipalId) ? [] : [
  { principalId: deployerPrincipalId, principalType: 'User', roleId: openAiUser }
]
var accountAssignments = concat(deployerOpenAi, [
  { principalId: functionPrincipalId, principalType: 'ServicePrincipal', roleId: openAiUser }
])

resource projectRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for a in projectAssignments: {
    scope: project
    name: guid(project.id, a.principalId, a.roleId)
    properties: {
      principalId: a.principalId
      principalType: a.principalType
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', a.roleId)
    }
  }
]

resource accountRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for a in accountAssignments: {
    scope: account
    name: guid(account.id, a.principalId, a.roleId)
    properties: {
      principalId: a.principalId
      principalType: a.principalType
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', a.roleId)
    }
  }
]

// プロジェクトとアカウントのマネージド ID（ID はデプロイ中に決まるので、ループに入れずに1つずつ書く）
var systemIdentityRoles = [foundryUser, openAiUser]

resource projectIdentityRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for roleId in systemIdentityRoles: {
    scope: account
    name: guid(account.id, project.id, 'project-identity', roleId)
    properties: {
      principalId: project.identity.principalId
      principalType: 'ServicePrincipal'
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleId)
    }
  }
]

resource accountIdentityRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for roleId in systemIdentityRoles: {
    scope: account
    name: guid(account.id, 'account-identity', roleId)
    properties: {
      principalId: account.identity.principalId
      principalType: 'ServicePrincipal'
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleId)
    }
  }
]

output accountName string = account.name
output accountId string = account.id
output projectEndpoint string = 'https://${account.properties.customSubDomainName}.services.ai.azure.com/api/projects/${project.name}'
output projectId string = project.id
output modelDeployment string = deployment.name
output embeddingDeployment string = embedding.name
