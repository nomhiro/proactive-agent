// Foundry のアカウント、プロジェクト、モデルのデプロイ。キーは無効にし、Entra だけで使う
param location string
param tags object
param resourceToken string
param deployerPrincipalId string
param functionPrincipalId string
param modelName string
param modelVersion string
param modelCapacity int = 50
@description('Foundry Memory の索引に使う埋め込みモデル（確認 5）')
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
  sku: { name: 'GlobalStandard', capacity: modelCapacity }
  properties: {
    model: { format: 'OpenAI', name: embeddingName, version: embeddingVersion }
  }
  dependsOn: [deployment] // 同じアカウントへのデプロイは1つずつ
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: account
  name: 'proj-spike'
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: 'proactive spike'
    description: 'harness 付きエージェントの確認用（使い捨て）'
  }
  dependsOn: [embedding]
}

// ロールは名前の変更中のため GUID で指定する（ドキュメントの注記どおり）
var foundryUser = '53ca6127-db72-4b80-b1b0-d745d6d5456d'
var foundryProjectManager = 'eadc314b-1a2d-4efa-be10-5d325db5065e'
// Memory ストアへの書き込みに要る（ないと 401。Memory のクイックスタートの前提）
var openAiUser = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

var assignments = [
  { principalId: deployerPrincipalId, principalType: 'User', roleId: foundryUser }
  { principalId: deployerPrincipalId, principalType: 'User', roleId: foundryProjectManager }
  { principalId: functionPrincipalId, principalType: 'ServicePrincipal', roleId: foundryUser }
  { principalId: deployerPrincipalId, principalType: 'User', roleId: openAiUser }
  { principalId: functionPrincipalId, principalType: 'ServicePrincipal', roleId: openAiUser }
]

resource roleAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for a in assignments: {
    scope: project
    name: guid(project.id, a.principalId, a.roleId)
    properties: {
      principalId: a.principalId
      principalType: a.principalType
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', a.roleId)
    }
  }
]

output projectEndpoint string = 'https://${account.properties.customSubDomainName}.services.ai.azure.com/api/projects/${project.name}'
output projectId string = project.id
output modelDeployment string = deployment.name
output embeddingDeployment string = embedding.name
