// Web アプリ（BFF と画面を1つのコンテナに入れる。Plan 4 決定 1）。
// - コンテナーレジストリは管理者ユーザーを無効にし、イメージはユーザー割り当てマネージド ID で取得する
// - サインインは Container Apps の組み込み認証（Entra）。クライアントシークレットは使わない
//   （シークレットなしでは ID トークンだけを受け取る暗黙的フローになる。キーを持たない方針のため）
// - BFF は返事の受け取りを裏で待たないので、ゼロまで縮んでよい。最大 1 台
// - サインインできるのは、アプリに割り当てた人だけ（デプロイした人を割り当てる）。デモのデータを消して作り直す
//   操作があるため、テナントの全員には開かない。デプロイした人が分からないときは、割り当てを求めない
extension microsoftGraphV1

param location string
param tags object
@minLength(13)
param resourceToken string
param environmentName string
param identityId string
param identityClientId string
param identityPrincipalId string
param logAnalyticsId string
param cosmosEndpoint string
param cosmosDatabase string
param foundryProjectEndpoint string
param memoryStoreName string
param webPubSubEndpoint string
param webPubSubHub string
@description('サインインを許す人（azd のデプロイした人）。空なら割り当てを求めない')
param principalId string = ''

var appName = 'ca-web-${resourceToken}'

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'cr${resourceToken}'
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

// 7f951dda-4ed3-4680-a7ca-43fe172d538d = AcrPull
resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: registry
  name: guid(registry.id, identityPrincipalId, 'acr-pull')
  properties: {
    principalId: identityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
  }
}

// ログは Azure Monitor に送り、診断設定で Log Analytics に入れる（ワークスペースの共有キーを使わない）
resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-${resourceToken}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: { destination: 'azure-monitor' }
  }
}

resource environmentLogs 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: environment
  name: 'logs'
  properties: {
    workspaceId: logAnalyticsId
    logs: [{ categoryGroup: 'allLogs', enabled: true }]
  }
}

var callbackUrl = 'https://${appName}.${environment.properties.defaultDomain}/.auth/login/aad/callback'

// サインイン用のアプリ登録。ID トークンの発行だけを有効にする
resource signInApp 'Microsoft.Graph/applications@v1.0' = {
  uniqueName: 'proactive-web-${resourceToken}'
  displayName: 'proactive-agent web (${environmentName})'
  signInAudience: 'AzureADMyOrg'
  web: {
    redirectUris: [callbackUrl]
    implicitGrantSettings: { enableIdTokenIssuance: true }
  }
  requiredResourceAccess: [
    {
      resourceAppId: '00000003-0000-0000-c000-000000000000' // Microsoft Graph
      resourceAccess: [{ id: 'e1fe6dd8-ba31-4d61-89e7-88639da4683d', type: 'Scope' }] // User.Read
    }
  ]
}

resource signInSp 'Microsoft.Graph/servicePrincipals@v1.0' = {
  appId: signInApp.appId
  appRoleAssignmentRequired: !empty(principalId)
}

// アプリが役割を持たないので、既定の役割 ID（すべて 0）で割り当てる
resource signInAssignment 'Microsoft.Graph/appRoleAssignedTo@v1.0' = if (!empty(principalId)) {
  appRoleId: '00000000-0000-0000-0000-000000000000'
  principalId: principalId
  resourceId: signInSp.id
}

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: appName
  location: location
  tags: union(tags, { 'azd-service-name': 'web' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identityId}': {} }
  }
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      ingress: { external: true, targetPort: 8000, transport: 'auto', allowInsecure: false }
      registries: [{ server: registry.properties.loginServer, identity: identityId }]
    }
    template: {
      containers: [
        {
          name: 'web'
          // 最初のイメージは仮のもの。azd deploy が web のイメージに差し替える
          image: 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'AZURE_CLIENT_ID', value: identityClientId }
            { name: 'WEB_STORE', value: 'cosmos' }
            { name: 'WEB_AUTH', value: 'easyauth' }
            { name: 'COSMOS_ENDPOINT', value: cosmosEndpoint }
            { name: 'COSMOS_DATABASE', value: cosmosDatabase }
            { name: 'FOUNDRY_PROJECT_ENDPOINT', value: foundryProjectEndpoint }
            { name: 'MEMORY_STORE_NAME', value: memoryStoreName }
            { name: 'WEBPUBSUB_ENDPOINT', value: webPubSubEndpoint }
            { name: 'WEBPUBSUB_HUB', value: webPubSubHub }
          ]
        }
      ]
      scale: { minReplicas: 0, maxReplicas: 1 }
    }
  }
  dependsOn: [acrPull]
}

resource auth 'Microsoft.App/containerApps/authConfigs@2024-03-01' = {
  parent: app
  name: 'current'
  properties: {
    platform: { enabled: true }
    globalValidation: {
      unauthenticatedClientAction: 'RedirectToLoginPage'
      redirectToProvider: 'azureactivedirectory'
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: signInApp.appId
          openIdIssuer: '${az.environment().authentication.loginEndpoint}${tenant().tenantId}/v2.0'
        }
        validation: { allowedAudiences: [] }
      }
    }
  }
  dependsOn: [signInSp]
}

output name string = app.name
output url string = 'https://${app.properties.configuration.ingress.fqdn}'
output registryEndpoint string = registry.properties.loginServer
