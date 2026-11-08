// Functions の実行とデプロイ用、HILS のログと解析のグラフ用。共有キーは使わない
param location string
param tags object
@minLength(3)
param resourceToken string
@description('デプロイする人の object ID。シードで HILS ログを置くため、Blob の書き込み権限を付ける（空なら付けない）')
param deployerPrincipalId string = ''

resource account 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'st${resourceToken}'
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    allowSharedKeyAccess: false
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource blob 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: account
  name: 'default'
}

resource containers 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = [
  for name in ['app-package', 'hils-logs', 'analysis-artifacts']: {
    parent: blob
    name: name
  }
]

// Storage Blob Data Contributor
var blobDataContributor = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'

resource deployerBlob 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(deployerPrincipalId)) {
  scope: account
  name: guid(account.id, deployerPrincipalId, blobDataContributor)
  properties: {
    principalId: deployerPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDataContributor)
  }
}

output name string = account.name
output blobEndpoint string = account.properties.primaryEndpoints.blob
output deploymentContainerUrl string = '${account.properties.primaryEndpoints.blob}app-package'
